# Menu Background Embedding

## Goal

When a Tkinter menu needs to look like its text blocks and buttons are embedded inside a background image, do not rely on true transparent child widgets. Instead, draw the background once and make each visual block reuse the matching local slice of that background.

This note summarizes the working approach used for `audrey-hall/audrey_hall/quick_menu.py` in Audrey Hall.

## What Does Not Work Well

- Using `-transparentcolor` for inner layout transparency.
- Making intermediate `Frame` backgrounds transparent and expecting lower widgets in the same window to show through.
- Stretching the background image directly to arbitrary menu width and height.

Why:

- `-transparentcolor` is window-level chroma-key transparency on Windows. Matching pixels go straight through to the desktop, not to sibling or lower widgets in the same window.
- Tkinter `Frame`/`Label` transparency is very limited. "Transparent" children do not naturally reveal sibling widgets below them.
- Direct resize-to-fit distorts artwork and makes embedded elements feel visually disconnected.

## Working Pattern

### 1. Use one root `Canvas` as the menu surface

- The menu background image is drawn once on a top-level `Canvas`.
- All visible blocks are then added on top of that `Canvas`.

In this project:

- `self._menu_canvas` is the root surface.
- `self._bg_image_id` stores the background image item.

### 2. Keep the image at original aspect ratio

- Read the original image size.
- Compute the final menu size from content needs.
- Expand the final menu width/height to match the image aspect ratio.
- Scale the image with `contain` logic and center it inside the menu.

Key fields in `quick_menu.py`:

- `self._header_bg_source`: original `PIL.Image`
- `self._menu_bg_image`: resized image currently shown
- `self._menu_bg_offset_x`, `self._menu_bg_offset_y`: centered offset after aspect-ratio scaling

### 3. Fake transparency with background slicing

For any header block or button that should look transparent:

- Create a small child `Canvas`
- Crop the exact matching rectangle from the already-scaled menu background
- Put that cropped image into the child canvas as its bottom layer
- Draw text, badges, hover states, borders, and indicators on top

This creates the illusion that the child is transparent while still being fully controllable.

In this project:

- `_register_surface_background(...)` stores each child surface region
- `_refresh_surface_background(...)` crops the correct local background slice
- `_shift_surface_backgrounds(...)` keeps crop coordinates aligned if content is repositioned

## Header Strategy

For non-button header content like `AURORA CONTROL`:

- Do not use a solid `Frame` with border by default
- Use a child `Canvas`
- Give it a cropped background slice from the main menu image
- Draw text directly with `create_text`
- Only keep intentional non-transparent accents like the version badge if needed

This avoids the "solid rectangle pasted on top of the artwork" look.

## Button Strategy

For menu buttons that should feel embedded:

- Default state:
  - no solid background
  - no border
  - no left indicator bar
  - only text and state labels
- Hover state:
  - draw the old card background
  - draw hover border
  - draw left accent indicator
  - update text colors as before

This makes buttons appear carved into the background in idle state, then rise visually on hover.

## Layout Strategy

To avoid background distortion:

1. Measure content first
2. Compute required minimum width and height
3. Expand final menu size to match the background image aspect ratio
4. Center the content region inside that larger ratio-correct menu
5. Shift all registered child background slice coordinates with the same offset

This is important. If content moves but slice coordinates do not, the fake transparency stops lining up with the artwork.

## Recommended Steps For Future UI Work

If another menu or panel needs the same effect:

1. Use a root `Canvas`
2. Load the background as `PIL.Image`
3. Keep final panel size aligned to the background image aspect ratio
4. Draw the scaled background once
5. For each visually transparent child region:
   - create a child `Canvas`
   - crop the corresponding local area from the scaled background
   - draw overlay text and hover decorations on top
6. Avoid window-level chroma-key transparency unless the desired result is actual desktop passthrough

## File Reference

Current implementation reference:

- `audrey-hall/audrey_hall/quick_menu.py`

Main helper methods:

- `_load_header_bg`
- `_update_menu_bg`
- `_register_surface_background`
- `_refresh_surface_background`
- `_shift_surface_backgrounds`
- `_create_header`
- `_create_menu_button`

## Short Prompt For Future AI Sessions

Use this if you need to continue or rebuild the same style:

"For Tkinter embedded-background UI, do not use `-transparentcolor` for inner pseudo-transparency. Use one root `Canvas` with a proportionally scaled background image, then give each header/button child canvas a cropped local slice of that background as its base layer. Default state should reveal the artwork; hover state can redraw card background, border, and indicators. Keep the outer panel size aligned to the background image aspect ratio and shift slice coordinates if content is repositioned." 
