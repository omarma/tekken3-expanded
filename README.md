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
| **Tekken 3** | USA, **SLUS-00402**: a `.cue` with its `.bin` files (one `.bin` per track, or a single `.bin` holding all three) |
| **Tekken Tag Tournament arcade ROM** | `tektagt.zip`, **non-merged**, World TEG2/VER.C1 |
| **Tekken 3 arcade ROM** *(optional)* | `tekken3.zip`, TET2/VER.E1, for the arcade difficulty levels |

**Platforms:** macOS on Intel and Apple Silicon (tested on macOS 15 and 26). Windows: **not tested yet**; the setup is there, reports are welcome.

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
4. When it is done, the game starts. Next time, **Setup Tekken 3.command** starts the game directly.

## Install on Windows *(not tested yet)*

1. Install [Python 3.12](https://www.python.org/downloads/) (keep "py launcher" and "tcl/tk" ticked) and [Git](https://git-scm.com/).
2. `git clone https://github.com/omarma/tekken3-expanded.git`, or download the ZIP of the [latest release](https://github.com/omarma/tekken3-expanded/releases/latest) and extract **all** of it with [7-Zip](https://www.7-zip.org/). Windows' own extractor can silently skip files whose path is too long: the setup then stops with a confusing error.
3. Put the `tekken3-expanded` folder on a short path without special characters, outside OneDrive (for example `C:\Games\tekken3-expanded`): the build creates deep paths that Windows may refuse otherwise.
4. Double-click **Setup Tekken 3.cmd**. The setup downloads its own compiler and MAME, then asks for your files (see [Where to put your game files](#where-to-put-your-game-files)).

## Troubleshooting

- **"Setup needs attention"**: the reason is in `.setup/setup.log`, inside the `tekken3-expanded` folder (the folder is hidden on macOS: press Cmd+Shift+. in Finder). Please [open an issue](https://github.com/omarma/tekken3-expanded/issues) and attach that file, with your OS and Python version (`python3 --version`, or `py --version` on Windows).
- **"This disc does not match…" or "The game files could not be prepared"** on Windows, with a disc you know is right: the folder is often incomplete (a partial extraction). Extract the ZIP again with 7-Zip, or use `git clone`. Then try: Python 3.12 (not 3.13 or newer), the folder on a short path outside OneDrive, then delete `.setup` and run the setup again.
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
