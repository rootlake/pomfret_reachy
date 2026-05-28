# Boo Hide — plan

## Goal

Reachy Mini **goes to sleep / hides** when the user says **“boo”** (substring match, case-insensitive).

## Approach

- **Python app** (Control / simulator): `ReachyMiniApp` main loop runs on the daemon connection.
- **Speech**: background thread using `speech_recognition` + Google Web Speech API when PyAudio + mic work (typical on laptop + wireless robot with mic path).
- **Simulator / no mic**: local settings page **“Simulate boo”** calls `POST /boo` so behavior is testable without audio.
- **Hide motion**: `reachy_mini.goto_sleep()` once per trigger, with a cooldown to avoid repeats.

## Open questions (optional later)

- Wake automatically after N seconds? (Currently: wake from Reachy Mini Control.)
- Offline STT (Whisper) instead of Google? (Heavier deps; conversation template is better for full voice stacks.)
