# Lukez Bunz phone app

A native Android / iOS shell (Capacitor 7) around the web app, so GPS keeps
recording with the screen off or another app open.

- **Live mode (default):** the app opens https://linzee7000.github.io/lukez-bunz/,
  so every push to `main` reaches the phones with no app rebuild.
- **Bundled mode:** `LB_BUNDLED=1 npm run sync` packs `index.html`, the icons and
  `data/` into the app. Works with no signal at start-up, but needs a rebuild
  for every change.

Background GPS comes from `@capacitor-community/background-geolocation`. A small
script at the top of `index.html` swaps `navigator.geolocation` for that plugin
when running inside the app (it does nothing in a normal browser), so the rest
of the app's GPS code is unchanged. On Android a "Lukez Bunz - Tracking the run"
notification shows while tracking; on iOS the blue location pill shows.

The app has its own storage, separate from Chrome/Safari: sync any unsent edits
in the browser before switching a phone over.

## Android

The GitHub Actions workflow "Android app" builds an APK whenever `app/` changes
(or from the Actions tab: Run workflow). The latest APK is always at
https://github.com/Linzee7000/lukez-bunz/releases/tag/android-latest (download
`lukez-bunz.apk`), then install it or push it out with Scalefusion.

To build on the Mac instead: install Android Studio, then

```bash
cd app
npm install
npm run android      # copies the web app, syncs, opens Android Studio
```

Samsung tip: set the app's battery use to **Unrestricted** (Settings > Apps >
Lukez Bunz > Battery), or Samsung may still stop it in the background.
Location permission "Allow only while using the app" is enough.

## iOS (needs the Mac + Xcode)

```bash
cd app
npm install
npm run ios          # opens Xcode
```

In Xcode: select the App target > Signing & Capabilities > pick your Team
(Apple developer account), then Run on a plugged-in iPhone, or
Product > Archive to send it to TestFlight. Packages are fetched by Swift
Package Manager, no CocoaPods needed.
