#!/bin/bash
# Builds "School System.app" and SchoolSystem.dmg on a Mac. Run from the kit folder:  bash build/mac/build_mac.sh
# Needs once: Python 3.9+ from python.org (or Homebrew). Customers need nothing.
set -e
cd "$(dirname "$0")/../.."
PY=${PYTHON:-python3}
$PY -m venv .venv-build && source .venv-build/bin/activate
pip install --upgrade pip pyinstaller
rm -rf dist build/pyi output; mkdir -p output
# make an .icns from the PNG
ICONSET=build/pyi/icon.iconset; mkdir -p $ICONSET
for s in 16 32 64 128 256 512; do sips -z $s $s assets/icon.png --out $ICONSET/icon_${s}x${s}.png >/dev/null; sips -z $((s*2)) $((s*2)) assets/icon.png --out $ICONSET/icon_${s}x${s}@2x.png >/dev/null; done
iconutil -c icns $ICONSET -o build/pyi/icon.icns
pyinstaller --noconfirm --clean --onedir --windowed --name "School System" --icon build/pyi/icon.icns \
  --osx-bundle-identifier com.okvtechnology.schoolsystem --add-data "manuals:manuals" --add-data "config.json:." \
  --workpath build/pyi --specpath build/pyi school_system.py
ARCH=$(uname -m)
STAGE=build/pyi/dmg; rm -rf $STAGE; mkdir -p $STAGE
cp -R "dist/School System.app" $STAGE/
cp assets/INSTRUCTIONS.txt $STAGE/
ln -s /Applications $STAGE/Applications
hdiutil create -volname "School System" -srcfolder $STAGE -ov -format UDZO "output/SchoolSystem-$ARCH.dmg"
echo "DONE: output/SchoolSystem-$ARCH.dmg"
