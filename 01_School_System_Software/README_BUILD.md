# School Result and Accounting Management System: build kit

This kit turns the program into **normal installers that do not need Python**:

| Platform | Result | Notes |
|---|---|---|
| Windows 7 SP1, 8, 10, 11 (32-bit and 64-bit) | `SchoolSystemSetup.exe` | One installer. A 32-bit build runs on both 32-bit and 64-bit Windows. |
| macOS (Intel and Apple silicon) | `SchoolSystem-x86_64.dmg` / `SchoolSystem-arm64.dmg` | Drag to Applications. |

I could not compile these in the environment where the kit was written (no Windows or Mac tools there), so **you build them once**. Pick the easy way:

## Easiest: build in the cloud with GitHub (no Windows PC or Mac needed)
1. Create a free GitHub account and a **private** repository. Upload everything in this kit (keep the folder structure, including `.github`).
2. Open the repository's **Actions** tab, choose **Build installers**, press **Run workflow**.
3. After a few minutes download the three artifacts: `SchoolSystemSetup-windows`, and the two Mac `.dmg` files.

## Or build on your own computer
* **Windows:** install Python 3.8 (32-bit) and Inno Setup 6, then double-click `build\windows\build_windows.bat`. Result: `output\SchoolSystemSetup.exe`.
* **Mac:** install Python 3 from python.org, open Terminal in this folder, run `bash build/mac/build_mac.sh`. Result: `output/SchoolSystem-<arch>.dmg`. Build once on an Intel Mac and once on an Apple-silicon Mac, or use the cloud route.

## Before you build (once)
1. **Your own licence key.** `pip install cryptography`, then `python tools/make_keys.py`. It patches your public key into the program and creates `private_key.pem` and `private_key_one_line.txt`. Paste the one-line key into Apps Script as the `PRIVATE_KEY` script property. Never share the private key. (The sample key that came with the first version of this kit was generated in a shared environment; replace it.)
2. **Your website address.** In `config.json` replace `YOUR_DEPLOYMENT_ID` with your Apps Script web app URL (see the website README).
3. Optional: put your own `assets/icon.ico`, and edit `assets/INSTRUCTIONS.txt` and `assets/EULA.txt`.

## What the Windows installer does
Installs to Program Files, keeps all school data in `C:\ProgramData\SchoolSystem` (so upgrades never touch data), opens the firewall for the program so phones on the school Wi-Fi can connect, optionally starts the system when the computer starts (scheduled task), adds Start-menu and desktop shortcuts, and a "Stop School System" shortcut. Uninstalling keeps the data folder.

## Mac notes
The app is not signed with an Apple developer certificate, so the first launch needs right-click, Open. To remove that prompt you need an Apple Developer account to sign and notarize the app.

## Make the download ZIP for customers
Make **two** ZIPs: one with `SchoolSystemSetup.exe` + `INSTRUCTIONS.txt` (Windows), one with the Mac `.dmg` file(s) + `INSTRUCTIONS.txt` (Mac). Upload both to Google Drive, share each as "Anyone with the link", copy each file ID, and paste them in the OKV admin dashboard under **Pricing and site, Download files** (Windows file ID and Mac file ID). The Windows and Mac download buttons across the website use them.

## Test checklist (do this once on a clean Windows 7/10/11 PC and a Mac)
Install, sign in as `admin` / `admin123`, add a pupil, enter scores with 1, 2 and 3 C.A tests, print a report sheet, press Phone (QR) and open the address on a phone, reboot (the system should come back by itself), then Admin > License and activate with a test code.
