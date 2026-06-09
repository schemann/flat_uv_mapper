# Flat UV Mapper

**Flat UV Mapper** is a Blender add-on for CSG-style planar face UV mapping with tile, offset, and rotation. It allows you to quickly apply and adjust planar UV maps on selected faces, similar to how texturing works in Hammer or other CSG editors.

## Features

- **Projection Modes:**
  - **Axis Aligned:** World-axis planar projection (Hammer/CSG style).
  - **Face Aligned:** Project along the face normal.
- **Adjustments:** Control Tile size (X/Y), Offset (X/Y), and Rotation.
- **Live Apply:** Reproject automatically when values change for instant feedback.
- **Fit to Face:** Normalize the projected UVs of the selection into the 0..1 range.
- **Pick From Face:** Read tile, offset, and rotation settings from the active face's current UVs.
- **Reset:** Quickly reset offset and rotation to defaults.

## Requirements

- Blender 4.2.0 or newer.

## Installation

1. Download the repository as a ZIP file or clone it.
2. In Blender, go to **Edit > Preferences > Add-ons**.
3. Click **Install...** and select the ZIP file (or the `.py` file if you prefer).
4. Enable the add-on by checking the box next to **Flat UV Mapper**.

## Usage

1. Enter **Edit Mode** on a Mesh object.
2. Open the Sidebar (press `N`) and navigate to the **Flat UV** tab.
3. Select the faces you want to map.
4. Adjust the projection mode, tile, offset, and rotation. If **Live Apply** is checked, changes will be visible immediately.
5. Use the operators (Apply, Fit to Face, Pick From Face, Reset) as needed to fine-tune your UV mapping.

## License

This project is licensed under the [GPL-3.0-or-later](LICENSE) license.