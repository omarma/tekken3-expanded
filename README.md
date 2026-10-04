# Tekken 3 Expanded

**Tekken 3 Expanded** puts the 18 characters Tekken Tag Tournament added to the roster into Tekken 3, playable in every mode and fought by the CPU. It runs on [Tekken3Recompiled](https://github.com/FishB0nes98/Tekken3Recompiled), the PC recompilation of Tekken 3.

DEV DIARY 1.2 : https://youtu.be/YvDqCwzFNps

> **No game files are included.** You provide your own Tekken 3 disc image and your own Tekken Tag Tournament and Tekken 3 arcade ROMs. The setup builds everything from them on your machine.

---

## Features

### The Tag Tournament roster
- **18 playable characters:** Kazuya, Jun, Kunimitsu, Michelle, Baek, Armor King, Bruce, Jack-2, P.Jack, Lee, Ganryu, Devil, Angel, Roger, Alex, Tetsujin, Wang, Unknown.
- **Tag page on the select screen:** press **L2 / R2** to switch rosters. It works in every mode, and P1 and P2 can each pick a different guest.
- **ALL Costumes Available** by pressing Punch, Kick or Start.
- **From TTT:** the voices, sounds, portraits and announcer calls, and each character's own strong-hit effect, fade-out included.
- **Closer to the arcade:** hands that close into each character's own fist, Devil's and Angel's wings that flap, faces that blink and shut their eyes when hit, metallic hit sounds for Jack-2 and P.Jack, the KO cry with Tekken 3's echo.
- **Unknown** works as in Tekken Tag Tournament: she fights with the TTT movesets and switches style with **L1**, from 23 styles.
- **Tetsujin** draws a random moveset every round from the TTT characters added to the game, and wears gold on **Start**.
- **Devil and Angel** fire the arcade's laser beams along their facing, Air Inferno upwards. The CPU side-steps them, and the Jacks go haywire when hit.
- **Panda and Tiger** show their own TTT portraits.
- **A hidden skin** is waiting to be found.

### TTT movesets for Tekken 3's cast
After you pick one of the 18 characters below, a **MOVESET** card lets you choose **TEKKEN 3** or **TEKKEN TAG TOURNAMENT**. The command list and Combo Training follow your choice.
Paul, Law, Lei, King, Yoshimitsu, Nina, Hwoarang, Xiaoyu, Eddy, Jin, Julia, Bryan, Heihachi, Anna, Kuma, Ogre, Gun Jack, True Ogre (with his fire).

The CPU draws its own moveset once per fight: set it in **Options → CPU MOVESET** (original, TTT or random).

### Combos and move lists
- **TTT characters:** each has their TTT move list and their own Combo Training, 88 combos in all.
- **Tekken 3's cast:** the move list switches to TTT when you pick the TTT moveset.
- **Practice:** ATTACK DATA shows "!" for every unguardable hit.

### CPU and modes
- **CPU opponents** in Arcade, Time Attack, Survival, Team Battle and Tekken Ball. Devil, Angel and Unknown are hidden sub-bosses.
- **A Tekken Force boss route** for every guest.

### Embu TTT
The attract-mode kata is performed by the TTT cast.

### Options
- **Difficulty:** the arcade levels, EASY to EX SUPER HARD, are in the Options menu.
- **16:9:** fixes for the stages, Tekken Ball and the VS handicap screen.
- **Unlocks:** everything is unlocked from the start.

---

## Optional add-on

The setup offers them as checkboxes. Leave them unticked and nothing changes.

| Add-on | What it does | Extra file needed |
|---|---|---|
| **Jin's red lightning** | Jin's strong hits use his red TTT lightning instead of the blue one. | None, the arcade ROM is enough |
| **TTT Cinematics** | Finish Arcade with Kazuya: his Tekken Tag Tournament ending plays in Tekken 3's engine, in place of his ending movie. For now, Kazuya's is the only ending. | None: it plays over Tekken 3's music |
| **TTT Cinematics music** | The ending's original music. | Your **Tekken Tag Tournament (USA) PS2 disc** (SLUS-20001) |

## Coming in a future release

- **More Tekken Tag Tournament endings** for TTT Cinematics.
- **Devil Jin, with his Tekken 5 moveset.**

---

## What you need

| File | Details |
|---|---|
| **Tekken 3** (PlayStation) | USA, **SLUS-00402** (Redump "Tekken 3 (USA)"): a `.cue` with its `.bin` files, one `.bin` per track or a single `.bin` holding all three |
| **Tekken Tag Tournament arcade ROM** | `tektagt.zip`: MAME set `tektagt`, *Tekken Tag Tournament (World, TEG2/VER.C1, set 1)*, **non-merged** |
| **Tekken 3 arcade ROM** *(optional)* | `tekken3.zip`: MAME set `tekken3`, *Tekken 3 (World, TET2/VER.E1)*, for the arcade difficulty levels |
| **Tekken Tag Tournament** (PlayStation 2) *(optional)* | USA, **SLUS-20001**: a `.cue`/`.bin` or `.iso`, only for the TTT Cinematics music |

The exact versions:

- **Tekken 3 disc**: its Track 1 `.bin` is 632,532,768 bytes, SHA-1 `68f32a8657376cb4d4504c160fd5e8ae4a4f18d6`.
- **`tektagt.zip`**: every chip included (non-merged: the set does not borrow files from a parent). Its program ROMs are `teg2verc1.2e` (SHA-1 `9e01ae64710d85eb9899d6fa6fd0a2152aee8c11`) and `teg2verc1.2j` (SHA-1 `529a11a1bbb8655534d7ec371f1c09e9e387ed11`). Other revisions (VER.B, set 2, the Japan or US releases) are not supported.
- **`tekken3.zip`**: its program ROMs are `tet2vere1.2e` (SHA-1 `3a5638c6ad40bfde6e12fdfd6d469f6ea5e9f4fb`) and `tet2vere1.2j` (SHA-1 `554d1e42886d6a6c9c5857e9cbd5d7c37d7a6e67`). A zip with only `tet1vere.2e` / `tet1vere.2j` as program ROMs is the TET1 revision: not supported.

What counts is the content of the files, not their names: sets made for older MAME versions name the same chips differently (for example `tet2vere.2e` for `tet2vere1.2e`) and work. The zip's own name does not matter either (a `tekken3ae.zip` holding the TET2 chips works).

To check a ROM zip yourself with MAME 0.289: copy it alone into an empty folder under the name `tektagt.zip` (or `tekken3.zip`), then run `mame -rompath <folder> -verifyroms tektagt` (or `tekken3`). It must say `romset ... is good`.

**Platforms:** macOS on Intel and Apple Silicon (tested on macOS 15 and 26). Windows 10 and 11 (tested on Windows 11 with Python 3.14). Steam Deck: experimental, with the Windows build and Proton (see [Steam Deck](#steam-deck-experimental)). Android phones: experimental, built on your computer by **Build Android APK** (see [Android](#android-experimental)).

## Where to put your game files

Anywhere you like: the setup asks for each file, and never moves or changes them.

- **Keep the disc files together**: the `.cue` and every `.bin` it lists in the same folder. Choose the `.cue`.
- **Don't unzip the arcade ROMs**: choose `tektagt.zip` and `tekken3.zip` as they are.
- **Tip:** put all of them in one folder (for example `Documents/Tekken3-files`). When you choose the disc, the setup fills in `tektagt.zip` and `tekken3.zip` by itself if they sit next to it.

On macOS without the setup window, drag each file onto the Terminal window when it asks, then press Return.

## Install on macOS

1. Install the tools with [Homebrew](https://brew.sh):
   ```bash
   xcode-select --install
   brew install cmake ninja sdl3 python@3.13 python-tk@3.13
   ```
   `python-tk` gives the setup its window; without it, the setup asks its questions in Terminal instead. MAME is not needed: the TTT1 characters and the arcade difficulty levels come straight from your ROM zips.
2. Get the mod:
   ```bash
   git clone https://github.com/omarma/tekken3-expanded.git
   ```
3. In the `tekken3-expanded` folder, double-click **Setup Tekken 3.command**, choose your files, tick the add-on if you want it, and start.
4. When it is done, the game's launcher opens: click **PLAY**. Next time, double-click **Tekken 3 Expanded** in the same folder (see [The launcher](#the-launcher)).

## Install on Windows

1. Install [Python](https://www.python.org/downloads/) 3.10 or later. In the installer, keep **py launcher** and **tcl/tk and IDLE** ticked. Nothing else is needed: the setup downloads its own compiler, without installing it on the system and without admin rights.
2. `git clone https://github.com/omarma/tekken3-expanded.git`, or download **Tekken3Expanded-x.y.z-PC.zip** from the [latest release](https://github.com/omarma/tekken3-expanded/releases/latest) and extract **all** of it with [7-Zip](https://www.7-zip.org/). Do not start the setup from inside the ZIP (double-clicking it in the ZIP's window): Windows then runs it from a temporary folder holding only part of the files. Windows' own extractor can silently skip files whose path is too long: the setup then stops with a confusing error.
3. Put the `tekken3-expanded` folder on a short path without special characters, outside OneDrive (for example `C:\Games\tekken3-expanded`): the build creates deep paths that Windows may refuse otherwise.
4. Double-click **Setup Tekken 3.cmd**. The setup downloads its own compiler, then asks for your files (see [Where to put your game files](#where-to-put-your-game-files)).
5. When it is done, the game's launcher opens: click **PLAY**. Next time, double-click **Tekken 3 Expanded.exe** in the same folder (see [The launcher](#the-launcher)). You can pin it to Start or send a shortcut to the desktop.

## Steam Deck (experimental)

The Steam Deck runs the Windows build through Proton: set the game up on a Windows PC, then copy it over. This hasn't been tested much yet: if you try it, please tell me how it went, working or not, in an [issue](https://github.com/omarma/tekken3-expanded/issues).

1. On a Windows PC, install Tekken 3 Expanded as above and check that it plays. To copy less, answer Yes to **Free up disk space** at the end of the setup.
2. Copy the whole `tekken3-expanded` folder to the Deck (USB stick, microSD card or network), for example to `/home/deck/Games/tekken3-expanded`.
3. On the Deck, in Desktop Mode, open Steam, then **Games → Add a Non-Steam Game to My Library → Browse**, and choose `tekken3-expanded/build-release/Tekken_3_Expanded.exe`. Coming from 1.1.x, where it was `Tekken_3_Recompiled.exe`: remove the old shortcut and add this one (the update deletes the old file).
4. In Steam, right-click the game → **Properties**:
   - **Start In**: `"/home/deck/Games/tekken3-expanded/"` (your folder, in quotes)
   - **Launch Options**: leave it empty. The game finds `game.toml` and the disc from its own folder; a `--disc` path typed here is read from a folder Proton may change, and the game then fails to find the disc.
   - **Compatibility**: tick **Force the use of a specific Steam Play compatibility tool**, then choose the latest Proton
   - You can rename the shortcut **Tekken 3 Expanded**.
5. Start it, in Desktop Mode or Game Mode. To go straight into the game with the controller, tick **Skip launcher on boot** in the launcher.

To update, update the folder on the PC, then copy it to the Deck again.

## Android (experimental)

**Build Android APK** makes the game for an Android phone: an APK file you install on the phone. It is the same game, with the characters and add-ons you choose, built on your computer from your own files. It needs no PC install: it asks for your files itself.

**What you need:**
- A Mac or a Windows PC to build it, prepared as for the PC game: on macOS, the Homebrew tools of [Install on macOS](#install-on-macos) step 1; on Windows, Python as in [Install on Windows](#install-on-windows) step 1.
- Your game files, as for the PC game (see [What you need](#what-you-need)).
- A 64-bit Android phone (arm64) with Android 9 or later. A controller is recommended; touch controls are built in.
- About 7 GB free on the computer the first time: the setup downloads Google's Android tools (about 1 GB) and a portable Java if you have none, into `.setup/android`. Nothing is installed on the system.
- About 2 GB free on the phone: the APK is about 1 GB, and the game copies your disc out of it the first time it starts.

**Build the APK:**
1. Download **Tekken3Expanded-x.y.z-Android.zip** from the [latest release](https://github.com/omarma/tekken3-expanded/releases/latest) and extract **all** of it (7-Zip on Windows), on a short path.
2. Double-click **Build Android APK.cmd** (macOS: **Build Android APK.command**), choose your files and the add-ons, and start.
3. The first build takes a while. When it is done, the window shows where the APK is: `Tekken3Expanded.apk`, in the `tekken3-expanded` folder.

Already playing the PC game? **Build Android APK** in the same folder builds the APK of that install, without asking for your files again.

**Install it:**
- Copy `Tekken3Expanded.apk` to the phone (USB cable, cloud drive, microSD card), then open it on the phone. Android asks you to allow installing apps from that source: allow it.
- Or, with the phone connected by USB and **USB debugging** on (Settings → About phone → tap **Build number** 7 times, then Settings → Developer options → **USB debugging**): `adb install -r Tekken3Expanded.apk`. The setup downloads `adb` into `.setup/android/platform-tools`. `Build Android APK` with `--install` does this for you.

The first start copies the game data out of the APK, with a progress bar. Later starts skip this. Without a controller, touch controls appear; press **Back** in the game to open its menu, where you can also move each touch button.

**Keep `.setup/android/release.keystore`** (and the `release.password` beside it). They sign the APK, and Android only installs an update over the game when it is signed with the same key. With a new key, you must uninstall the game first, and that deletes its memory cards on the phone.

**If something goes wrong on the phone,** connect it by USB with USB debugging on, start the game, then run `adb logcat -d -s psxrecomp` and attach what it prints to an [issue](https://github.com/omarma/tekken3-expanded/issues). If the build itself stops, attach `.setup/setup.log` (with Build Android APK: what its window printed).

## The launcher

The setup puts **Tekken 3 Expanded** (`.exe` on Windows, `.app` on macOS) next to the setup script: double-click it to play; it opens the setup instead when an update needs it. **Setup Tekken 3** always opens the setup window, to set up again or change your files and options.

The game opens on its launcher, where you set the controls, the display and the audio, then click **PLAY**. To go straight into the game, tick **Skip launcher on boot**. To bring the launcher back, in Terminal or the command prompt, in the `tekken3-expanded` folder, run `"Setup Tekken 3.cmd" --settings` (macOS: `./"Setup Tekken 3.command" --settings`), then untick it.

## Updating to a new version

Update the folder you already set up: no full reinstall. The setup keeps its tools, the TTT1 characters it imported and the build, so an update takes about a minute instead of the first setup's 17.

1. Get the new files into your existing `tekken3-expanded` folder:
   - with git: `git pull` in the folder;
   - with the PC ZIP: extract it, then copy **the contents** of its `tekken3-expanded-x.y.z` folder into your existing folder, replacing every file (7-Zip: *Yes to All*).
2. Start **Setup Tekken 3.cmd** (or **Setup Tekken 3.command**). The setup window opens with your files already filled in: click **Update & play**. Changes to the TTT1 characters are applied to your install, without a new import when the update allows it; otherwise the setup imports them again from your `tektagt.zip`.

Don't move `.setup`, `workspace` or `build-release` to a new folder: they remember their location, and the build would fail there.

**From 1.1.x to 1.2:**
- The update imports the TTT1 characters again from your `tektagt.zip`: keep it where the setup can find it. MAME is no longer needed.
- The game is now `build-release/Tekken_3_Expanded.exe` (it was `Tekken_3_Recompiled.exe`, which the update deletes). On a Steam Deck, add the new one to Steam again.

## Disk space

A finished install takes several GB, but only part of it is the game. Inside the `tekken3-expanded` folder:

| Folder | What it is | Needed to play |
|---|---|---|
| `build-release` | The game, its mods and the imported TTT characters | Yes |
| `disc` | The setup's copy of your Tekken 3 disc, read by the game | Yes |
| `saves` | Your memory cards | Yes |
| `.setup/venv`, `.setup/ready.json` | What lets **Tekken 3 Expanded** start the game directly | Yes |
| `.setup/tools`, `.setup/downloads` | Windows only: the compiler the setup downloaded | No |
| `.setup/android` | Android only: the Android tools and **the APK's signing key** (keep `release.keystore`) | For the APK |
| `.setup/android/downloads` | Android only: the Android tools' archives, already unpacked | No |
| `build-android`, `Tekken3Expanded.apk` | Android only: the Android build and the APK | No |
| `workspace` | The TTT1 import's intermediate files (the result is in `build-release`) | No |
| `generated` | The recompiled game code: the game checks for it at every start | Yes |
| `.setup/disc-tracks` | Only for a single-`.bin` disc: its tracks, split for the setup | No |
| `build-release/**/CMakeFiles` | The build's intermediate files (`.o`, `.obj`) | No |

At the end of the setup, it offers to delete what is marked **No** for you (it asks once; answer No and it won't ask again). You can also delete those yourself and keep playing. The cost comes with the next update that rebuilds the game: instead of about a minute, it can take as long as the first setup (about 17 minutes: downloads and build), and an update that imports the TTT1 characters again needs your `tektagt.zip` again (the TTT1 changes that need no new import are applied to the copy beside the game). Keep your original game files either way.

## Troubleshooting

- **"Setup needs attention"**: the reason is in `.setup/setup.log`, inside the `tekken3-expanded` folder (the folder is hidden on macOS: press Cmd+Shift+. in Finder). Please [open an issue](https://github.com/omarma/tekken3-expanded/issues) and attach that file, with your OS and Python version (`python3 --version`, or `py --version` on Windows).
- **"This disc does not match…" or "The game files could not be prepared"** on Windows, with a disc you know is right: the folder is often incomplete (a partial extraction). Extract the ZIP again with 7-Zip, or use `git clone`. Then try the folder on a short path outside OneDrive, then delete `.setup` and run the setup again.
- Each character import keeps its own log in `workspace/ttt1-import/logs/`.
- To start over, delete the `.setup`, `workspace`, `generated`, `disc` and `build-release` folders.

## Controls

| Where | Button | Action |
|---|---|---|
| Select screen | L2 / R2 | Switch to the Tag page and back |
| Select screen | Punch / Kick / Start | Pick a costume |
| MOVESET card | ← / → | Choose TEKKEN 3 or TEKKEN TAG TOURNAMENT |
| MOVESET card | ✕ or Start | Confirm |
| MOVESET card | ○ | Go back to the grid |
| In a fight, as Unknown | L1 | Switch style |

### Keyboard

| Button | Player 1 | Player 2 |
|---|---|---|
| Directions | Arrow keys | I J K L |
| ✕ / ○ / □ / △ | X / S / Z / A | Keypad 1 / 2 / 4 / 5 |
| L1 / R1 | Q / W | U / O |
| L2 / R2 | E / R | Keypad 7 / 9 |
| Start / Select | Return / Right Shift | Keypad Enter / Backspace |

On a Mac, player 2's buttons are F G V B (△ ○ □ ✕), 7 / 9 (L2 / R2) and P (Start). The keys are positions on a US keyboard: on an AZERTY keyboard, "A" is the key marked Q.

To change them, open [the launcher](#the-launcher). Set a player's input source to **Keyboard**, click **Configure**, then click a button and press the new key. Each button takes a second key or a mouse button in the next column. The keys are saved in `build-release/keybinds.ini`.

---

## Credits

- [Tekken3Recompiled](https://github.com/FishB0nes98/Tekken3Recompiled) by FishB0nes98, and [psxrecomp](https://github.com/RetroPortingToolKit/psxrecomp) by mstan.
- Tekken, Tekken 3 and Tekken Tag Tournament are trademarks of Bandai Namco Entertainment. This is a non-commercial fan project, not affiliated with or endorsed by Bandai Namco.

## License

**Disclaimer:** This project is a fan-made, non-commercial endeavor and is in no way affiliated with, authorized, maintained, sponsored, or endorsed by Bandai Namco Entertainment Inc. or any of its affiliates. "Tekken" and all associated trademarks, characters, and assets are registered trademarks of Bandai Namco Entertainment Inc.

**No Copyrighted Material:** This repository **does not contain any copyrighted game assets, ROMs, or ISOs**. It only provides open-source tools, scripts, and source code intended to be used with a legally owned and dumped copy of the game. Users must provide their own original game data to use this software.

**Source Code License:**
The original tools, build scripts, and modifications provided in this repository are licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE), like the upstream project (see LICENSE).
*(Note: Any third-party libraries or upstream decompilation code retain their original respective licenses).*
