param([string]$Out = "../TombaRecomp\build-clean\launcher_shot.png")
$p = Get-Process psx-runtime -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Output "no window"; exit 1 }
Write-Output ("hwnd=" + $p.MainWindowHandle + " title=" + $p.MainWindowTitle)
$sig = @'
using System;
using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
  public struct RECT { public int left, top, right, bottom; }
  public struct POINT { public int x, y; }
}
'@
Add-Type -TypeDefinition $sig 2>$null
$h = $p.MainWindowHandle
[W]::SetWindowPos($h, [IntPtr](-1), 0,0,0,0, 0x40 -bor 0x1 -bor 0x2) | Out-Null
[W]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 400
$r = New-Object W+RECT
[W]::GetClientRect($h, [ref]$r) | Out-Null
$tl = New-Object W+POINT
[W]::ClientToScreen($h, [ref]$tl) | Out-Null
$w = $r.right - $r.left; $ht = $r.bottom - $r.top
Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap($w, $ht)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($tl.x, $tl.y, 0, 0, (New-Object System.Drawing.Size($w, $ht)))
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output ("saved " + $Out + " (" + $w + "x" + $ht + ")")
