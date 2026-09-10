#!/usr/bin/env bash
# Stage a CLEAN Steam Workshop upload folder - only what RimWorld loads, plus legal.
#
# Why: RimWorld's in-game uploader ships the ENTIRE mod folder
# (SteamUGC.SetItemContent over the mod dir, no .rwignore, no filtering). Uploading
# the repo directly would publish tools/, test/, docs/, .idea/, .git/ to the Workshop.
# So upload from the folder this stages, never from the repo.
#
# Allowlist, not blocklist: only RimWorld-recognized content dirs + LICENSE/NOTICE are
# copied; anything new in the repo stays out of the release by default.
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:-$REPO/../.publish/$(basename "$REPO")}"

rm -rf "$DEST"
mkdir -p "$DEST"
for item in About Patches Defs Assemblies Textures Sounds Languages Common LICENSE NOTICE; do
    [ -e "$REPO/$item" ] && cp -r "$REPO/$item" "$DEST/"
done
# Carry the Workshop item link if this mod is already published, so upload updates it.
[ -f "$REPO/About/PublishedFileId.txt" ] && cp "$REPO/About/PublishedFileId.txt" "$DEST/About/"

echo "Clean upload staged at: $DEST"
echo "Shipping files:"
find "$DEST" -type f | sed "s#$DEST/##" | sort
echo
echo "To publish: point RimWorld's Mods/ entry at the staged folder (or use SteamCMD),"
echo "then upload. After the first publish, copy the generated About/PublishedFileId.txt"
echo "back into the repo's About/."
