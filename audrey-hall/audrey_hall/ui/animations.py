def animate_toplevel_slide_in(window, final_x, final_y, width, height, offset_y=8, steps=5, interval_ms=18):
    start_y = final_y - max(0, int(offset_y))
    steps = max(1, int(steps))

    def _tick(step):
        progress = step / steps
        current_y = int(start_y + (final_y - start_y) * progress)
        window.geometry(f'{width}x{height}+{final_x}+{current_y}')
        if step < steps:
            window.after(interval_ms, lambda: _tick(step + 1))

    _tick(0)
