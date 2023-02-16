#!/bin/sh
# Create a folder (named dmg) to prepare our DMG in (if it doesn't already exist).
mkdir -p dist/dmg
# Empty the dmg folder.
rm -r dist/dmg/*
# Copy the app bundle to the dmg folder.
cp -r "dist/DeutscheBahnReservierungssuche.app" dist/dmg
# If the DMG already exists, delete it.
test -f "dist/DeutscheBahnReservierungssuche.dmg" && rm "dist/DeutscheBahnReservierungssuche.dmg"
create-dmg \
  --volname "DeutscheBahnReservierungssuche" \
  --volicon "dist/DeutscheBahnReservierungssuche/assets/app_icon.icns" \
  --window-pos 200 120 \
  --window-size 600 300 \
  --icon-size 100 \
  --icon "DeutscheBahnReservierungssuche.app" 175 120 \
  --hide-extension "DeutscheBahnReservierungssuche.app" \
  --app-drop-link 425 120 \
  "dist/DeutscheBahnReservierungssuche.dmg" \
  "dist/dmg/"