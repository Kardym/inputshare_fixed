# Shortcuts

The shortcuts following are available after connection:

| Shortcut | Description |
| --- | --- |
| `<Alt>+<Shift>+e` | Toggle the control between your computer and your Android device |
| `<Alt>+<Shift>+q` | Quit the Program |
| `F1` | Multi-task Switching |
| `F2` | Return to Home |
| `F3` | Back |
| `F4` | Previous Media |
| `F5` | Play / Pause Media |
| `F6` | Next Media |
| `F7` | Volume Down |
| `F8` | Volume Up |
| `F9` | Brightness Down |
| `F10` | Brightness Up |
| `F11` | Screen Sleep |
| `F12` | Wake Up |
| Mouse side button `X1` | Back |
| Mouse side button `X2` | Open Notification |

The shortcuts following are available after connection and not sharing:

| Shortcut | Description |
| --- | --- |
| `<Alt>+UP` | Scroll Up |
| `<Alt>+DOWN` | Scroll Down |
| `<Alt>+[` | Previous Media |
| `<Alt>+]` | Next Media |
| `<Alt>+\` | Play / Pause Media |

## Two-finger gestures (while controlling Android)

- Hold Alt at the Android cursor to remember the first touch position. Both touches go down together when you click or use the wheel. Move the cursor, then hold the left mouse button and drag for the second touch.
- With Alt held, wheel up to zoom in or wheel down to zoom out. Release Alt to release all touches.
- Alt+Shift+E switches control; Alt+Shift+Q exits. These combinations cancel an active gesture.
- Requires Android to report the scrcpy mouse cursor in `dumpsys input`; gestures are disabled if its position is unavailable. Keyboard-only sharing does not use touch gestures.

### Two-finger pan

While controlling Android, hold **M3 (mouse wheel button)** and move the mouse to drag two fingers together in the mouse direction. Release M3 to lift both fingers. The finger spacing stays fixed, including at screen edges, so this pans rather than zooms. No Alt key is needed. Alt+left-drag and Alt+wheel still provide pinch-to-zoom.
