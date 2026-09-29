# Tekken 3 Expanded

**Tekken 3 Expanded** puts the 18 characters Tekken Tag Tournament added to the roster into Tekken 3, playable in every mode and fought by the CPU. It runs on [Tekken3Recompiled](https://github.com/FishB0nes98/Tekken3Recompiled), the PC recompilation of Tekken 3.

TRAILER : https://youtu.be/Th9PMY7SybA

> **No game files are included.** You provide your own Tekken 3 disc image and your own Tekken Tag Tournament and Tekken 3 arcade ROMs. The setup builds everything from them on your machine.

---

## Features

### The Tag Tournament roster
- **18 playable characters:** Kazuya, Jun, Kunimitsu, Michelle, Baek, Armor King, Bruce, Jack-2, P.Jack, Lee, Ganryu, Devil, Angel, Roger, Alex, Tetsujin, Wang, Unknown.
- **Tag page on the select screen:** press **L2 / R2** to switch rosters. It works in every mode, and P1 and P2 can each pick a different guest.
- **ALL Costumes Available** by pressing Punch, Kick or Start.
- **From TTT:** the voices, sounds, portraits and announcer calls, and each character's own strong-hit effect.
- **Unknown** works as in Tekken Tag Tournament: she fights with the TTT movesets and switches style with **L1**, from 23 styles.
- **Tetsujin** draws a random moveset every round from the TTT characters added to the game.
- **Devil and Angel** fire lasers that hit.
- **A hidden skin** is waiting to be found.

### TTT movesets for Tekken 3's cast
After you pick one of the 14 characters below, a **MOVESET** card lets you choose **TEKKEN 3** or **TEKKEN TAG TOURNAMENT**. The command list, Combo Training and the CPU follow your choice.
Paul, Law, Lei, King, Yoshimitsu, Nina, Hwoarang, Xiaoyu, Eddy, Jin, Julia, Bryan, Heihachi, Anna.

### Combos and move lists
- **TTT characters:** each has their TTT move list and their own Combo Training, 88 combos in all.
- **Tekken 3's cast:** the move list switches to TTT when you pick the TTT moveset.

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

The setup offers it as a checkbox. Leave it unticked and nothing changes.

| Add-on | What it does | Extra file needed |
|---|---|---|
| **Jin's red lightning** | Jin's strong hits use his red TTT lightning instead of the blue one. | None, the arcade ROM is enough |

## Coming in a future release

- **Kazuya's Tekken Tag Tournament ending**, replayed in Tekken 3's engine.
- **Devil Jin, with his Tekken 5 moveset.**

---

## What you need

| File | Details |
|---|---|
| **Tekken 3** (PlayStation) | USA, **SLUS-00402** (Redump "Tekken 3 (USA)"): a `.cue` with its `.bin` files, one `.bin` per track or a single `.bin` holding all three |
| **Tekken Tag Tournament arcade ROM** | `tektagt.zip`: MAME set `tektagt`, *Tekken Tag Tournament (World, TEG2/VER.C1, set 1)*, **non-merged** |
| **Tekken 3 arcade ROM** *(optional)* | `tekken3.zip`: MAME set `tekken3`, *Tekken 3 (World, TET2/VER.E1)*, for the arcade difficulty levels |

The exact versions:

- **Tekken 3 disc**: its Track 1 `.bin` is 632,532,768 bytes, SHA-1 `68f32a8657376cb4d4504c160fd5e8ae4a4f18d6`.
- **`tektagt.zip`**: every chip included (non-merged: the set does not borrow files from a parent). Its program ROMs are `teg2verc1.2e` (SHA-1 `9e01ae64710d85eb9899d6fa6fd0a2152aee8c11`) and `teg2verc1.2j` (SHA-1 `529a11a1bbb8655534d7ec371f1c09e9e387ed11`). Other revisions (VER.B, set 2, the Japan or US releases) are not supported.
- **`tekken3.zip`**: its program ROMs are `tet2vere1.2e` (SHA-1 `3a5638c6ad40bfde6e12fdfd6d469f6ea5e9f4fb`) and `tet2vere1.2j` (SHA-1 `554d1e42886d6a6c9c5857e9cbd5d7c37d7a6e67`). A zip with only `tet1vere.2e` / `tet1vere.2j` as program ROMs is the TET1 revision: not supported.

What counts is the content of the files, not their names: sets made for older MAME versions name the same chips differently (for example `tet2vere.2e` for `tet2vere1.2e`) and work. The zip's own name does not matter either (a `tekken3ae.zip` holding the TET2 chips works).

To check a ROM zip yourself with MAME 0.289: copy it alone into an empty folder under the name `tektagt.zip` (or `tekken3.zip`), then run `mame -rompath <folder> -verifyroms tektagt` (or `tekken3`). It must say `romset ... is good`.

**Platforms:** macOS on Intel and Apple Silicon (tested on macOS 15 and 26). Windows 10 and 11 (tested on Windows 11 with Python 3.14).

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
   brew install cmake ninja sdl3 mame python@3.13 python-tk@3.13
   ```
   `python-tk` gives the setup its window; without it, the setup asks its questions in Terminal instead.
2. Get the mod:
   ```bash
   git clone https://github.com/omarma/tekken3-expanded.git
   ```
3. In the `tekken3-expanded` folder, double-click **Setup Tekken 3.command**, choose your files, tick the add-on if you want it, and start.
4. When it is done, the game's launcher opens: click **PLAY**. Next time, **Setup Tekken 3.command** opens the launcher directly (see [The launcher](#the-launcher)).

## Install on Windows

1. Install [Python](https://www.python.org/downloads/) 3.10 or later. In the installer, keep **py launcher** and **tcl/tk and IDLE** ticked. Nothing else is needed: the setup downloads its own compiler and MAME, without installing them on the system and without admin rights.
2. `git clone https://github.com/omarma/tekken3-expanded.git`, or download the ZIP of the [latest release](https://github.com/omarma/tekken3-expanded/releases/latest) and extract **all** of it with [7-Zip](https://www.7-zip.org/). Do not start the setup from inside the ZIP (double-clicking it in the ZIP's window): Windows then runs it from a temporary folder holding only part of the files. Windows' own extractor can silently skip files whose path is too long: the setup then stops with a confusing error.
3. Put the `tekken3-expanded` folder on a short path without special characters, outside OneDrive (for example `C:\Games\tekken3-expanded`): the build creates deep paths that Windows may refuse otherwise.
4. Double-click **Setup Tekken 3.cmd**. The setup downloads its own compiler and MAME, then asks for your files (see [Where to put your game files](#where-to-put-your-game-files)).
5. When it is done, the game's launcher opens: click **PLAY**. Next time, **Setup Tekken 3.cmd** opens the launcher directly (see [The launcher](#the-launcher)).

## The launcher

The game opens on its launcher, where you set the controls, the display and the audio, then click **PLAY**. To go straight into the game, tick **Skip launcher on boot**. To bring the launcher back, in Terminal or the command prompt, in the `tekken3-expanded` folder, run `"Setup Tekken 3.cmd" --settings` (macOS: `./"Setup Tekken 3.command" --settings`), then untick it.

## Updating to a new version

Update the folder you already set up: no full reinstall. The setup keeps its tools, the TTT1 characters it imported and the build, so an update takes about a minute instead of the first setup's 17.

1. Get the new files into your existing `tekken3-expanded` folder:
   - with git: `git pull` in the folder;
   - with the ZIP: extract it, then copy **the contents** of its `tekken3-expanded-x.y.z` folder into your existing folder, replacing every file (7-Zip: *Yes to All*).
2. Start **Setup Tekken 3.cmd** (or **Setup Tekken 3.command**). The setup window opens with your files already filled in: click **Set up & play**.

Don't move `.setup`, `workspace` or `build-release` to a new folder: they remember their location, and the build would fail there.

## Disk space

A finished install takes several GB, but only part of it is the game. Inside the `tekken3-expanded` folder:

| Folder | What it is | Needed to play |
|---|---|---|
| `build-release` | The game, its mods and the imported TTT characters | Yes |
| `disc` | The setup's copy of your Tekken 3 disc, read by the game | Yes |
| `saves` | Your memory cards | Yes |
| `.setup/venv`, `.setup/ready.json` | What lets **Setup Tekken 3** start the game directly | Yes |
| `.setup/tools`, `.setup/downloads` | Windows only: the compiler and MAME the setup downloaded | No |
| `workspace` | The TTT1 import's intermediate files (the result is in `build-release`) | No |
| `generated` | The recompiled game code, used only to build it | No |
| `.setup/disc-tracks` | Only for a single-`.bin` disc: its tracks, split for the setup | No |

You can delete the folders marked **No** and keep playing. The cost comes with the next update that rebuilds the game: instead of about a minute, it runs the whole first setup again (about 17 minutes: downloads, TTT1 import and build), and it needs your disc image and `tektagt.zip` again. Keep your original game files either way.

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
