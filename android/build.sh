#!/bin/sh
# Build silly-cat.apk with the raw SDK toolchain (no gradle).
set -e
cd "$(dirname "$0")"

# d8/R8 in build-tools 34 is incompatible with newer JDKs; pin 17.
export JAVA_HOME=/opt/homebrew/opt/openjdk@17
export PATH="$JAVA_HOME/bin:$PATH"

SDK=${ANDROID_HOME:-/opt/homebrew/share/android-commandlinetools}
BT="$SDK/build-tools/34.0.0"
JAR="$SDK/platforms/android-34/android.jar"

python3 tools/gen_asset.py

rm -rf build
mkdir -p build/classes build/dex

javac -source 8 -target 8 -bootclasspath "$JAR" \
    -d build/classes src/com/sillycat/meow/*.java

"$BT/d8" --lib "$JAR" --release --output build/dex \
    build/classes/com/sillycat/meow/*.class

"$BT/aapt" package -f -M AndroidManifest.xml -A assets \
    -I "$JAR" -F build/meow.unsigned.apk
(cd build/dex && "$BT/aapt" add ../meow.unsigned.apk classes.dex)

"$BT/zipalign" -f 4 build/meow.unsigned.apk build/meow.aligned.apk

KS=debug.keystore
[ -f "$KS" ] || keytool -genkeypair -keystore "$KS" -alias androiddebugkey \
    -storepass android -keypass android -keyalg RSA -validity 10000 \
    -dname "CN=Android Debug,O=Android,C=US" 2>/dev/null

"$BT/apksigner" sign --ks "$KS" --ks-pass pass:android \
    --out build/silly-cat.apk build/meow.aligned.apk

ls -la build/silly-cat.apk
