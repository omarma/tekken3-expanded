package com.tekken3expanded;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.res.AssetFileDescriptor;
import android.content.res.AssetManager;
import android.text.TextUtils;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * The game's data folder. The APK carries the build folder (laid out as
 * build-release on PC, plus the disc) under assets/data; it is copied into
 * the app's internal storage after each install or update, and the runtime
 * runs from there. Files the game writes itself (memory cards, settings) are
 * not in the APK and are left alone.
 *
 * The disc's track files and the mods' PNG textures are the exception: the
 * APK stores them uncompressed (by zip), and the game reads them from the APK
 * in place. Each gets a placeholder instead of a copy (see
 * psxrecomp/runtime/src/android_apk_file.c): a sparse file of the file's size,
 * which takes no space, whose first bytes say where the file lies in the APK.
 * A track the build packed (tools/android/disc_pack.py: losslessly compressed,
 * starting with PSXPACK1) gets a placeholder of the original track's size
 * that names the packed file; the runtime unpacks it as it reads.
 */
final class GameData {
    interface Progress { void update(long done, long total); }

    private static final String DATA = "data";
    private static final String STAMP = ".apk-data-stamp";
    private static final String FILES = ".apk-data-files";
    private static final String SLICE_MAGIC = "psxrecomp-apk-slice\n";
    private static final String PACK_MAGIC = "psxrecomp-apk-pack\n";
    private static final byte[] PACKED_TRACK = "PSXPACK1".getBytes(StandardCharsets.US_ASCII);
    /** Disc files read from the APK in place (when stored uncompressed). */
    private static final String[] IN_PLACE = { ".bin", ".img", ".iso", ".chd" };
    /** The runtime reads a placeholder's first 4 KB and only takes files at least that big. */
    private static final int HEADER_MAX = 4096;

    private GameData() {}

    /** True when the data of the installed APK is already in place. */
    static boolean ready(Context context) {
        return stamp(context).equals(readText(new File(context.getFilesDir(), STAMP)));
    }

    static void prepare(Context context, Progress progress) throws IOException {
        AssetManager assets = context.getAssets();
        File root = context.getFilesDir();
        List<String> files = new ArrayList<>();
        list(assets, DATA, "", files);
        String apk = context.getApplicationInfo().sourceDir;
        long total = 0;
        for (String f : files) {
            long length = length(assets, DATA + "/" + f);
            // In place: nothing to copy, unless too small for a placeholder.
            if (!inPlace(f) || (length >= 0 && length < HEADER_MAX)) total += Math.max(0, length);
        }

        long[] done = { 0 };
        byte[] buffer = new byte[1024 * 1024];
        for (String f : files) {
            File to = new File(root, f);
            // A placeholder also replaces the full copy an older version made.
            if (inPlace(f) && placeholder(assets, DATA + "/" + f, apk, to)) continue;
            copy(assets, DATA + "/" + f, to, buffer, done, total, progress);
        }
        // Remove what the previous APK brought and this one no longer does
        // (e.g. a test APK's launch-args.txt).
        Set<String> now = new HashSet<>(files);
        for (String old : readText(new File(root, FILES)).split("\n")) {
            if (!old.isEmpty() && !now.contains(old)) new File(root, old).delete();
        }
        writeText(new File(root, FILES), TextUtils.join("\n", files));
        writeText(new File(root, STAMP), stamp(context));
    }

    static String readText(File file) {
        try (InputStream in = new FileInputStream(file)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[16 * 1024];
            int read;
            while ((read = in.read(buffer)) != -1) out.write(buffer, 0, read);
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            return "";
        }
    }

    private static String stamp(Context context) {
        try {
            PackageInfo info = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
            // The APK's path is in it too: the placeholders name it, and it
            // changes when the app is moved (e.g. to an SD card).
            return info.lastUpdateTime + ":" + info.getLongVersionCode() + ":"
                    + context.getApplicationInfo().sourceDir;
        } catch (Exception e) {
            return "unknown";
        }
    }

    private static void list(AssetManager assets, String path, String relative, List<String> out)
            throws IOException {
        String[] children = assets.list(path);
        if (children == null || children.length == 0) {
            out.add(relative);
            return;
        }
        for (String child : children) {
            list(assets, path + "/" + child, relative.isEmpty() ? child : relative + "/" + child, out);
        }
    }

    /** Size of an asset; -1 when unknown. */
    private static long length(AssetManager assets, String path) {
        try (AssetFileDescriptor fd = assets.openFd(path)) {
            return fd.getLength();
        } catch (IOException e) {
            // Compressed: an asset's stream knows its uncompressed size.
            try (InputStream in = assets.open(path)) {
                return in.available();
            } catch (IOException e2) {
                return -1;
            }
        }
    }

    private static boolean inPlace(String file) {
        String name = file.toLowerCase(Locale.ROOT);
        // The texture packs' PNG (read with fopen by the runtime, hd_load_image).
        if (file.startsWith("mods/")) return name.endsWith(".png");
        if (!file.startsWith("disc/")) return false;
        for (String extension : IN_PLACE) {
            if (name.endsWith(extension)) return true;
        }
        return false;
    }

    /**
     * Writes the placeholder of a file stored uncompressed in the APK; false
     * when it is compressed or too small (then it is copied).
     */
    private static boolean placeholder(AssetManager assets, String from, String apk, File to)
            throws IOException {
        long offset, length;
        try (AssetFileDescriptor fd = assets.openFd(from)) {
            offset = fd.getStartOffset();
            length = fd.getLength();
        } catch (IOException e) {
            offset = length = -1;
        }
        long packed = packedSize(assets, from);
        if (packed >= 0 && (length < 0 || packed < HEADER_MAX)) {
            // Copied, it would be the packed bytes under the track's name.
            throw new IOException(from + " is packed but cannot be read in place");
        }
        if (length < 0) return false;
        String magic = packed >= 0 ? PACK_MAGIC : SLICE_MAGIC;
        long size = packed >= 0 ? packed : length;
        byte[] header = (magic + offset + " " + length + "\n" + apk + "\n")
                .getBytes(StandardCharsets.UTF_8);
        // A smaller file is simply copied.
        if (header.length > HEADER_MAX || size < HEADER_MAX) return false;
        File parent = to.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs()) {
            throw new IOException("Cannot create " + parent);
        }
        File partial = new File(to.getPath() + ".partial");
        try (RandomAccessFile out = new RandomAccessFile(partial, "rw")) {
            out.setLength(0);
            out.write(header);
            out.setLength(size);   // the rest is a hole: no space used
        }
        if (!partial.renameTo(to)) throw new IOException("Cannot write " + to);
        return true;
    }

    /** The original size of a packed track (PSXPACK1 header), or -1. */
    private static long packedSize(AssetManager assets, String from) throws IOException {
        byte[] head = new byte[16];
        int got = 0;
        try (InputStream in = assets.open(from)) {
            int read;
            while (got < head.length && (read = in.read(head, got, head.length - got)) > 0) {
                got += read;
            }
        }
        if (got < head.length) return -1;
        for (int i = 0; i < PACKED_TRACK.length; i++) {
            if (head[i] != PACKED_TRACK[i]) return -1;
        }
        long size = 0;
        for (int i = 15; i >= 8; i--) size = size << 8 | (head[i] & 0xFF);
        return size;
    }

    private static void copy(AssetManager assets, String from, File to, byte[] buffer,
                             long[] done, long total, Progress progress) throws IOException {
        File parent = to.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs()) {
            throw new IOException("Cannot create " + parent);
        }
        File partial = new File(to.getPath() + ".partial");
        try (InputStream in = assets.open(from); OutputStream out = new FileOutputStream(partial)) {
            int read;
            while ((read = in.read(buffer)) != -1) {
                out.write(buffer, 0, read);
                done[0] += read;
                progress.update(done[0], total);
            }
        }
        if (!partial.renameTo(to)) throw new IOException("Cannot write " + to);
    }

    private static void writeText(File file, String text) throws IOException {
        try (OutputStream out = new FileOutputStream(file)) {
            out.write(text.getBytes(StandardCharsets.UTF_8));
        }
    }
}
