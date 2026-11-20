# Ergonomic Training Station — React UI Starter

The New Session and Session Analysis pages use the station service for recording and posture-analysis results.

## Tabs
- Home
- New Session
- Session Analysis
- Cameras

## Run
```powershell
npm install
npm run dev
```

## Recommended eventual architecture
React UI -> authenticated web backend -> station-local capture/OpenPose service.

Use institutional SSO rather than storing resident passwords in this application.
