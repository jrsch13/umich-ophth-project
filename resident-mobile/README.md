# Resident Mobile

An Expo SDK 58 and TypeScript app for reviewing session results on iPhone and Android. Residents and administrators use their existing station accounts. The station API determines which sessions each user can open.

## Install and start

Use Node.js 22.13 or newer. From the repository root in PowerShell:

```powershell
cd resident-mobile
npm.cmd ci
Copy-Item .env.example .env.local
```

Edit `.env.local` to point to your device-reachable station API. For example:

```dotenv
EXPO_PUBLIC_API_BASE_URL=https://station-dev.example.edu:8443
```

Use the real HTTPS station address, including any API path prefix. Treat this value as public app configuration. Restart Metro after changing it.

```powershell
npm.cmd start -- --lan
```

Run the backend separately. Set up the identity database and accounts using the [station-service instructions](../station-service/README.md). Mobile sign-in uses `POST /auth/token`, which requires HTTPS outside the backend's local loopback development mode.

## Connect a phone to the development API

1. Connect the phone and workstation to the same permitted network. Use a DNS name that resolves to the station or its HTTPS reverse proxy from the phone. Use a TLS certificate for that name that the device and app trust.
2. Run the station API behind the HTTPS proxy, or serve TLS directly from Uvicorn. For direct TLS, run the following from `station-service/` after configuring the three environment variables with your LAN bind address and PEM file paths.

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app:app --host $env:STATION_LAN_ADDRESS --port 8443 --ssl-certfile $env:STATION_CERT_PEM --ssl-keyfile $env:STATION_KEY_PEM
   ```

3. Allow the API port, and Metro port `8081` for LAN bundling, on the approved development network. Open the API’s `/health` URL from the phone to verify DNS, TLS, and network access. Point `.env.local` at that API’s base URL. Expo’s development tunnel can carry the JavaScript bundle, while the API still needs its own reachable HTTPS address.
4. Install Expo Go for SDK 58, or use a compatible native development build. Scan the QR code printed by Metro with Expo Go on Android or the Camera app on iPhone. If Expo Go on iPhone prompts for account pairing, sign in to Expo CLI with `npx.cmd expo login` and sign in to Expo Go with the same account. [Expo Go downloads](https://expo.dev/go) · [Expo device setup](https://docs.expo.dev/get-started/start-developing/)
5. Sign in with an invited resident or admin account. Use a completed session that the account can already open on desktop. Select a posture, tap the chart, relaunch to check session restoration, then log out.

For an Android emulator, boot the emulator in Android Studio and press `a` in Metro, or run `npm.cmd run android`. The Android emulator’s `10.0.2.2` host alias can route to a server on the workstation, and the HTTPS certificate must match the hostname or address in the API URL. A trusted station DNS name is usually simpler. On macOS, start an Xcode iOS simulator and press `i`, or run `npm run ios`. Windows developers can test iOS with a physical iPhone.

## Account and media behavior

- The API returns a one-hour Bearer token. SecureStore saves the token, expiration time, and matching API base URL in Android Keystore-backed storage or the iOS Keychain. The password and role are held only in memory. The app verifies identity with `/auth/me` after login and on reopen.
- Requests use HTTPS with certificate verification. A protected `401` clears the saved token and returns to Login. If the API is unreachable during restore, the app keeps the secure record and offers retry or logout. Logout clears SecureStore and requests server revocation when the API is reachable.
- The list displays the sessions returned by `GET /sessions`. Admin owner email is shown when provided. Processing and failed sessions remain visible. Detail refreshes when a pending or processing session changes status.
- The app renders reference percentages, trial assessed, categories, and point values from the existing API. The shaded chart bands use the returned point category keys, and the selected point shows the corresponding score or adjustment.
- Native sessions currently report `review_media_available: false`. The app shows point details and a short media availability message. A frame request is made only when the API reports `true` and a point is selected. Successful frames are held in memory for display.

## Verification

```powershell
npm.cmd run test
npm.cmd run typecheck
npm.cmd run lint
npx.cmd expo export --platform android --output-dir dist/android
npx.cmd expo export --platform ios --output-dir dist/ios
```

The component tests simulate Expo SecureStore and API responses. Use a physical device or emulator to validate native credential persistence, device networking, and touch behavior.

## Deployment beyond development

Provide an approved HTTPS API accessible to devices, organizational access controls and a database deployment, signed mobile builds with distribution identifiers, and device acceptance testing. Store and review session data under the institution’s privacy and retention requirements. Centralize the session catalog and analysis data if residents need access across workstations. Remote image review additionally needs an authorized media-serving path and storage pipeline before the API can advertise available review media.
