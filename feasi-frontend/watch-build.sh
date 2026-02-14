#!/bin/bash
# Auto-rebuild frontend on file changes → instantly live on ngrok
DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$DIR/src"

echo "Watching $SRC for changes..."
echo "Frontend will auto-rebuild → ngrok serves updated version"
echo "Press Ctrl+C to stop"

fswatch -o -e ".*" -i "\\.jsx$" -i "\\.js$" -i "\\.css$" -i "\\.html$" "$SRC" "$DIR/index.html" | while read; do
  echo ""
  echo "$(date '+%H:%M:%S') Change detected — rebuilding..."
  cd "$DIR" && npm run build 2>&1 | tail -3
  echo "$(date '+%H:%M:%S') Live on ngrok ✓"
done
