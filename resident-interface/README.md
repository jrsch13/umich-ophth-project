# Ergonomic Training Station — React UI Starter

Visual placeholder only. No camera capture, OpenPose, authentication, database, or session-processing functionality is connected yet.

## Tabs
- Home
- New
- History
- Cameras

## Run
```powershell
npm install
npm run dev
```

## Recommended eventual architecture
React UI -> authenticated web backend -> station-local capture/OpenPose service.

Use institutional SSO rather than storing resident passwords in this application.
