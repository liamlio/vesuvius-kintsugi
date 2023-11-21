import tkinter as tk
import glob
import tifffile
from tkinter import filedialog, PhotoImage, ttk
from PIL import Image, ImageTk
import numpy as np
import zarr
from collections import deque
import threading
import math
import os
import sys

Image.MAX_IMAGE_PIXELS = None

class VesuviusKintsugi:
    def __init__(self):
        self.overlay_alpha = 255
        self.barrier_mask = None  # New mask to act as a barrier for flood fill
        self.editing_barrier = False  # False for editing label, True for editing barrier
        self.max_propagation_steps = 100  # Default maximum propagation steps
        self.show_barrier = True
        self.voxel_data = None
        self.prediction_data = None
        self.photo_img = None
        self.th_layer = 0
        self.resized_img = None
        self.z_index = 0
        self.pencil_size = 0
        self.click_coordinates = None
        self.threshold = [10]
        self.log_text = None
        self.zoom_level = 1
        self.max_zoom_level = 15
        self.drag_start_x = None
        self.drag_start_y = None
        self.image_position_x = 0
        self.image_position_y = 0
        self.pencil_cursor = None  # Reference to the circle representing the pencil size
        self.flood_fill_active = False  # Flag to control flood fill
        self.history = []  # List to store a limited history of image states
        self.max_history_size = 3  # Maximum number of states to store
        self.mask_data = None
        self.show_mask = True  # Default to showing the mask
        self.show_image = True
        self.show_prediction = True
        self.initial_load = True
        self.init_ui()

    def load_data(self):
        dir_path = filedialog.askdirectory(title="Select Directory")

        if not dir_path:
            return

        try:
            # Check if the directory contains Zarr or TIFF files
            if os.path.exists(os.path.join(dir_path, '.zarray')):
                # Load the Zarr data into the voxel_data attribute
                self.voxel_data = np.array(zarr.open(dir_path, mode='r'))
            elif glob.glob(os.path.join(dir_path, '*.tif')):
                # Load TIFF slices into a 3D numpy array using memory-mapped files
                tiff_files = sorted(glob.glob(os.path.join(dir_path, '*.tif')), key=lambda x: int(os.path.basename(x).split('.')[0]))
                slices = [tifffile.memmap(f) for f in tiff_files]
                self.voxel_data = np.stack(slices, axis=0)
                self.update_log(f"Data loaded successfully {self.voxel_data.shape}.")
            else:
                self.update_log("Directory does not contain recognizable Zarr or TIFF files.")
                return

            self.mask_data = np.zeros_like(self.voxel_data)
            self.barrier_mask = np.zeros_like(self.voxel_data)
            self.z_index = 0
            if self.voxel_data is not None:
                self.threshold = [10 for _ in range(self.voxel_data.shape[0])]
            self.initial_load = True
            self.update_display_slice()
            self.file_name = os.path.basename(dir_path)
            self.root.title(f"Vesuvius Kintsugi - {self.file_name}")
            self.bucket_layer_slider.configure(from_=0, to=self.voxel_data.shape[0] - 1)
            self.bucket_layer_slider.set(0)
            self.update_log(f"Data loaded successfully.")
        except Exception as e:
            self.update_log(f"Error loading data: {e}")

    def load_prediction(self):
        if self.voxel_data is None:
            self.update_log("No voxel data loaded. Load voxel data first.")
            return

        # File dialog to select prediction PNG file
        pred_file_path = filedialog.askopenfilename(title="Select Prediction PNG", filetypes=[("PNG files", "*.png")])

        if pred_file_path:
            try:
                # Load the prediction PNG file
                loaded_prediction = Image.open(pred_file_path)
                
                # Convert the image to a NumPy array
                prediction_data_np = np.array(loaded_prediction)
                
                # Calculate padding and remove it
                '''
                pad0 = (64 - self.voxel_data.shape[1] % 64) # 64 tile size
                pad1 = (64 - self.voxel_data.shape[2] % 64)
                if pad0 or pad1:
                    prediction_data_np = prediction_data_np[:-pad0, :-pad1]
                '''
                self.prediction_data = prediction_data_np
                # Check if the dimensions match
                if self.prediction_data.shape[:2] == self.voxel_data.shape[1:]:
                    self.update_display_slice()
                    self.update_log("Prediction loaded successfully.")
                else:
                    self.update_log("Error: Prediction dimensions do not match the voxel data dimensions.")
            except Exception as e:
                self.update_log(f"Error loading prediction: {e}")

    def load_mask(self):
        if self.voxel_data is None:
            self.update_log("No voxel data loaded. Load voxel data first.")
            return

            # Prompt to save changes if there are any unsaved changes
        if self.history:
            if not tk.messagebox.askyesno("Unsaved Changes", "You have unsaved changes. Do you want to continue without saving?"):
                return

        # File dialog to select mask file
        mask_file_path = filedialog.askdirectory(
            title="Select Label Zarr File")
            

        if mask_file_path:
            try:
                loaded_mask = zarr.open(mask_file_path, mode='r')
                if loaded_mask.shape == self.voxel_data.shape:
                    self.mask_data = loaded_mask
                    self.update_display_slice()
                    self.update_log("Label loaded successfully.")
                else:
                    self.update_log("Error: Label dimensions do not match the voxel data dimensions.")
            except Exception as e:
                    self.update_log(f"Error loading mask: {e}")

    def save_image(self):
        if self.mask_data is not None:
            # Construct the default file name for saving
            base_name = os.path.splitext(os.path.basename(self.file_name))[0]
            default_save_file_name = f"{base_name}_label.zarr"
            parent_directory = os.path.join(self.file_name, os.pardir)
            # Open the file dialog with the proposed file name
            save_file_path = filedialog.asksaveasfilename(
                initialdir=parent_directory,
                title="Select Directory to Save Mask Zarr",
                initialfile=default_save_file_name,
                filetypes=[("Zarr files", "*.zarr")]
            )

            if save_file_path:
                try:
                    # Save the Zarr array to the chosen file path
                    zarr.save_array(save_file_path, self.mask_data)
                    self.update_log(f"Mask saved as Zarr in {save_file_path}")
                except Exception as e:
                    self.update_log(f"Error saving mask as Zarr: {e}")
        else:
            self.update_log("No mask data to save.")

    def update_threshold_layer(self, layer):
        try:
            self.th_layer = int(float(layer))
            self.bucket_layer_var.set(f"{self.th_layer}")

            # Update the Bucket Threshold Slider to the current layer's threshold value
            current_threshold = self.threshold[self.th_layer]
            self.bucket_threshold_var.set(f"{current_threshold}")
            # You may need to adjust this line depending on how the slider is named in your code
            self.bucket_threshold_slider.set(current_threshold)  

            self.update_log(f"Layer {self.th_layer} selected, current threshold is {current_threshold}.")
        except ValueError:
            self.update_log("Invalid layer value.")

    def update_threshold_value(self, val):
        try:
            self.threshold[self.th_layer] = int(float(val))
            self.bucket_threshold_var.set(f"{int(float(val))}")
            self.update_log(f"Layer {self.th_layer} threshold set to {self.threshold[self.th_layer]}.")
        except ValueError:
            self.update_log("Invalid threshold value.")

    def threaded_flood_fill(self):
        if self.click_coordinates and self.voxel_data is not None:
            # Run flood_fill_3d in a separate thread
            thread = threading.Thread(target=self.flood_fill_3d, args=(self.click_coordinates,))
            thread.start()
        else:
            self.update_log("No starting point or data for flood fill.")

    def flood_fill_3d(self, start_coord):
        self.flood_fill_active = True
        target_color = self.voxel_data[start_coord]
        queue = deque([start_coord])
        visited = set()

        counter = 0
        while self.flood_fill_active and queue and counter < self.max_propagation_steps:
            cz, cy, cx = queue.popleft()

            if (cz, cy, cx) in visited or not (0 <= cz < self.voxel_data.shape[0] and 0 <= cy < self.voxel_data.shape[1] and 0 <= cx < self.voxel_data.shape[2]):
                continue

            visited.add((cz, cy, cx))

            if self.barrier_mask[cz, cy, cx] != 0:
                continue

            if abs(int(self.voxel_data[cz, cy, cx]) - int(target_color)) <= self.threshold[cz]:
                self.mask_data[cz, cy, cx] = 1
                counter += 1
                for dz in [-1, 0, 1]:
                    for dx in [-1, 0, 1]:
                        for dy in [-1, 0, 1]:
                            if dz == 0 and dx == 0 and dy == 0:
                                continue
                            queue.append((cz + dz, cy + dy, cx + dx))

            if counter % 10 == 0:
                self.root.after(1, self.update_display_slice)
        if self.flood_fill_active == True:
            self.flood_fill_active = False
            self.update_log("Flood fill ended.")

    def stop_flood_fill(self):
        self.flood_fill_active = False
        self.update_log("Flood fill stopped.")

    def save_state(self):
        # Save the current state of the image before modifying it
        if self.voxel_data is not None:
            if len(self.history) == self.max_history_size:
                self.history.pop(0)  # Remove the oldest state
            self.history.append(self.mask_data.copy())

    def undo_last_action(self):
        if self.history:
            self.mask_data = self.history.pop() 
            self.update_display_slice()
            self.update_log("Last action undone.")
        else:
            self.update_log("No more actions to undo.")

    def on_canvas_press(self, event):
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def on_canvas_drag(self, event):
        if self.drag_start_x is not None and self.drag_start_y is not None:
            dx = event.x - self.drag_start_x
            dy = event.y - self.drag_start_y
            self.image_position_x += dx
            self.image_position_y += dy
            self.update_display_slice()
            self.drag_start_x, self.drag_start_y = event.x, event.y

    def on_canvas_pencil_drag(self, event):
        if self.mode.get() == "pencil" or self.mode.get() == "eraser":
            self.save_state()
            self.color_pixel(self.calculate_image_coordinates(event))

    def on_canvas_release(self, event):
        self.drag_start_x = None
        self.drag_start_y = None

    def resize_with_aspect(self, image, target_width, target_height, zoom=1):
        original_width, original_height = image.size
        zoomed_width, zoomed_height = int(original_width * zoom), int(original_height * zoom)
        aspect_ratio = original_height / original_width
        new_height = int(target_width * aspect_ratio)
        new_height = min(new_height, target_height)
        return image.resize((zoomed_width, zoomed_height), Image.Resampling.NEAREST)

    def resize_to_fit_canvas(self, image, canvas_width, canvas_height):
        """Resize image to fit the canvas while maintaining aspect ratio."""
        original_width, original_height = image.size
        aspect_ratio = original_width / original_height

        if canvas_width / canvas_height > aspect_ratio:
            new_width = int(aspect_ratio * canvas_height)
            new_height = canvas_height
        else:
            new_width = canvas_width
            new_height = int(canvas_width / aspect_ratio)

        self.zoom_level = min(new_width / original_width, new_height / original_height)

        return image.resize((new_width, new_height), Image.Resampling.NEAREST)
    
    def update_display_slice(self):
        if self.voxel_data is not None:
            target_width_xy = self.canvas.winfo_width()
            target_height_xy = self.canvas.winfo_height()
                      
            # Convert the current slice to an RGBA image
            if self.show_image:
                # Normalize the uint16 data to uint8
                if self.voxel_data.dtype == np.uint16:
                    img_data = self.voxel_data[self.z_index, :, :].astype('float32')
                    img_data = (img_data / np.max(img_data) * 255).astype('uint8')
                else:
                    img_data = self.voxel_data[self.z_index, :, :].astype('uint8')
                img = Image.fromarray(img_data).convert('L').convert('RGBA')
            else:
                img = Image.fromarray(np.zeros_like(self.voxel_data[self.z_index, :, :], dtype='uint8')).convert('RGBA')

            # Only overlay the mask if show_mask is True
            if self.mask_data is not None and self.show_mask:
                mask = np.uint8(self.mask_data[self.z_index, :, :] * self.overlay_alpha)
                yellow = np.zeros_like(mask, dtype=np.uint8)
                yellow[:, :] = 255  # Yellow color
                mask_img = Image.fromarray(np.stack([yellow, yellow, np.zeros_like(mask), mask], axis=-1), 'RGBA')

                # Overlay the mask on the original image
                img = Image.alpha_composite(img, mask_img)

            if self.barrier_mask is not None and self.show_barrier:
                barrier = np.uint8(self.barrier_mask[self.z_index, :, :] * self.overlay_alpha)
                red = np.zeros_like(barrier, dtype=np.uint8)
                red[:, :] = 255  # Red color
                barrier_img = Image.fromarray(np.stack([red, np.zeros_like(barrier), np.zeros_like(barrier), barrier], axis=-1), 'RGBA')

                # Overlay the barrier mask on the original image
                img = Image.alpha_composite(img, barrier_img)

            if self.prediction_data is not None and self.show_prediction:
                pred = np.uint8(self.prediction_data[:, :] * self.overlay_alpha)
                blue = np.zeros_like(pred, dtype=np.uint8)
                blue[:, :] = 255  # Red color
                pred_img = Image.fromarray(np.stack([np.zeros_like(pred), np.zeros_like(pred), blue, pred], axis=-1), 'RGBA')

                # Overlay the barrier mask on the original image
                img = Image.alpha_composite(img, pred_img)

                    # Resize the image with aspect ratio
            if self.initial_load:
                img = self.resize_to_fit_canvas(img, target_width_xy, target_height_xy)
                self.initial_load = False
            else:
                img = self.resize_with_aspect(img, target_width_xy, target_height_xy, zoom=self.zoom_level)

            # Convert back to a format that can be displayed in Tkinter
            self.resized_img = img.convert('RGB')
            self.photo_img = ImageTk.PhotoImage(image=self.resized_img)
            self.canvas.create_image(self.image_position_x, self.image_position_y, anchor=tk.NW, image=self.photo_img)
            self.canvas.tag_raise(self.z_slice_text)
            self.canvas.tag_raise(self.cursor_pos_text)

    def update_info_display(self):
        self.canvas.itemconfigure(self.z_slice_text, text=f"Z-Slice: {self.z_index}")
        if self.click_coordinates:
            try:
                _, cursor_y, cursor_x = self.calculate_image_coordinates(self.click_coordinates)
            except:
                cursor_x, cursor_y = 0, 0
            self.canvas.itemconfigure(self.cursor_pos_text, text=f"Cursor Position: ({cursor_x}, {cursor_y})")



    def on_canvas_click(self, event):
        self.save_state()
        img_coords = self.calculate_image_coordinates(event)
        if self.mode.get() == "bucket":
            if self.flood_fill_active == True:
                self.update_log("Last flood fill hasn't finished yet.")
            else:
                # Assuming the flood fill functionality
                self.click_coordinates = img_coords
                self.update_log("Starting flood fill...")
                self.threaded_flood_fill()  # Assuming threaded_flood_fill is implemented for non-blocking UI
        elif self.mode.get() == "pencil":
            # Assuming the pencil (pixel editing) functionality
            self.color_pixel(img_coords)  # Assuming color_pixel is implemented

    def calculate_image_coordinates(self, input):
        if input is None:
            return 0, 0, 0  # Default values
        if isinstance(input, tuple):
                _, y, x = input
        elif hasattr(input, 'x') and hasattr(input, 'y'):
                x, y = input.x, input.y
        else:
            # Handle unexpected input types
            raise ValueError("Input must be a tuple or an event object")
        if self.voxel_data is not None:
            original_image_height, original_image_width = self.voxel_data[self.z_index].shape

            # Dimensions of the image at the current zoom level
            zoomed_width = original_image_width * self.zoom_level
            zoomed_height = original_image_height * self.zoom_level

            # Adjusting click position for panning
            pan_adjusted_x = x - self.image_position_x
            pan_adjusted_y = y - self.image_position_y

            # Calculate the position in the zoomed image
            zoomed_image_x = max(0, min(pan_adjusted_x, zoomed_width))
            zoomed_image_y = max(0, min(pan_adjusted_y, zoomed_height))

            # Scale back to original image coordinates
            img_x = int(zoomed_image_x / self.zoom_level)
            img_y = int(zoomed_image_y / self.zoom_level)

            # Debugging output
            #print(f"Clicked at: ({x}, {y}), Image Coords: ({img_x}, {img_y})")

            return self.z_index, img_y, img_x
    
    def color_pixel(self, img_coords):
        z_index, center_y, center_x = img_coords
        if self.voxel_data is not None:
            # Calculate the square bounds of the circle
            min_x = max(0, center_x - self.pencil_size)
            max_x = min(self.voxel_data.shape[2] - 1, center_x + self.pencil_size)
            min_y = max(0, center_y - self.pencil_size)
            max_y = min(self.voxel_data.shape[1] - 1, center_y + self.pencil_size)

        if self.mode.get() in ["pencil", "eraser"]:
            # Decide which mask to edit based on editing_barrier flag
            target_mask = self.barrier_mask if self.editing_barrier else self.mask_data
            mask_value = 1 if self.mode.get() == "pencil" else 0
            for y in range(min_y, max_y + 1):
                for x in range(min_x, max_x + 1):
                    # Check if the pixel is within the circle's radius
                    if math.sqrt((x - center_x) ** 2 + (y - center_y) ** 2) <= self.pencil_size:
                            target_mask[z_index, y, x] = mask_value
            self.update_display_slice()

    
    def update_pencil_size(self, val):
        self.pencil_size = int(float(val))
        self.pencil_size_var.set(f"{self.pencil_size}")
        self.update_log(f"Pencil size set to {self.pencil_size}")

    def update_pencil_cursor(self, event):
        # Remove the old cursor representation
        if self.pencil_cursor:
            self.canvas.delete(self.pencil_cursor)
            self.update_display_slice()

        if self.mode.get() == "pencil":
            color = "yellow" if not self.editing_barrier else "red"
        if self.mode.get() == "eraser":
            color = "white"
        if self.mode.get() == "eraser" or self.mode.get() == "pencil":
            radius = self.pencil_size * self.zoom_level  # Adjust radius based on zoom level
            self.pencil_cursor = self.canvas.create_oval(event.x - radius, event.y - radius, event.x + radius, event.y + radius, outline=color, width=2)
        self.click_coordinates = (self.z_index, event.y, event.x)
        self.update_info_display()
            
    def scroll_or_zoom(self, event):
        # Adjust for different platforms
        ctrl_pressed = False
        if sys.platform.startswith('win'):
            # Windows
            ctrl_pressed = event.state & 0x0004
            delta = event.delta
        elif sys.platform.startswith('linux') or sys.platform.startswith('darwin'):
            # Linux or macOS
            ctrl_pressed = event.state & 4
            delta = 1 if event.num == 4 else -1

        if ctrl_pressed:
            self.zoom(delta)
        else:
            self.scroll(delta)

    def scroll(self, delta):
        if self.voxel_data is not None:
            # Update the z_index based on scroll direction
            delta = 1 if delta > 0 else -1
            self.z_index = max(0, min(self.z_index + delta, self.voxel_data.shape[0] - 1))
            self.update_display_slice()


    def zoom(self, delta):
        zoom_amount = 0.1  # Adjust the zoom sensitivity as needed
        if delta > 0:
            self.zoom_level = min(self.max_zoom_level, self.zoom_level + zoom_amount)
        else:
            self.zoom_level = max(1, self.zoom_level - zoom_amount)
        self.update_display_slice()

    def toggle_mask(self):
        # Toggle the state
        self.show_mask = not self.show_mask
        # Update the variable for the Checkbutton
        self.show_mask_var.set(self.show_mask)
        # Update the display to reflect the new state
        self.update_display_slice()
        self.update_log(f"Label {'shown' if self.show_mask else 'hidden'}.\n")

    def toggle_barrier(self):
        # Toggle the state
        self.show_barrier = not self.show_barrier
        # Update the variable for the Checkbutton
        self.show_barrier_var.set(self.show_barrier)
        # Update the display to reflect the new state
        self.update_display_slice()
        self.update_log(f"Barrier {'shown' if self.show_barrier else 'hidden'}.\n")

    def toggle_image(self):
        # Toggle the state
        self.show_image = not self.show_image
        # Update the variable for the Checkbutton
        self.show_image_var.set(self.show_image)
        # Update the display to reflect the new state
        self.update_display_slice()
        self.update_log(f"Image {'shown' if self.show_image else 'hidden'}.\n")

    def toggle_prediction(self):
        # Toggle the state
        self.show_prediction = not self.show_prediction
        # Update the variable for the Checkbutton
        self.show_prediction_var.set(self.show_prediction)
        # Update the display to reflect the new state
        self.update_display_slice()
        self.update_log(f"Ink predicton {'shown' if self.show_prediction else 'hidden'}.\n")

    def toggle_editing_mode(self):
        # Toggle between editing label and barrier
        self.editing_barrier = not self.editing_barrier
        self.update_log(f"Editing {'Barrier' if self.editing_barrier else 'Label'}")

    def update_alpha(self, val):
        self.overlay_alpha = int(float(val))
        self.update_display_slice()

    def show_help(self):
        help_window = tk.Toplevel(self.root)
        help_window.title("Info")
        help_window.geometry("800x700")  # Adjust size as necessary
        help_window.resizable(True, True)

        # Text widget with a vertical scrollbar
        help_text_widget = tk.Text(help_window, wrap="word", width=40, height=30)  # Adjust width and height as needed
        help_text_scrollbar = tk.Scrollbar(help_window, command=help_text_widget.yview)
        help_text_widget.configure(yscrollcommand=help_text_scrollbar.set)

        # Pack the scrollbar and text widget
        help_text_scrollbar.pack(side="right", fill="y")
        help_text_widget.pack(side="left", fill="both", expand=True)


        info_text = """Vesuvius Kintsugi: A tool for labeling 3D Zarr images for the Vesuvius Challenge (scrollprize.org).

Commands Overview:
- Icons (Top, Left to Right):
  1. Open Zarr 3D Image: Load image data from a Zarr directory.
  2. Open Zarr 3D Label: Load label data from a Zarr directory.
  3. Save Zarr 3D Label: Save current label data to a Zarr file.
  4. Undo Last Action: Revert the last change made to the label or barrier.
  5. Brush Tool: Edit labels or barriers with a freehand brush.
  6. Eraser Tool: Erase parts of the label or barrier.
  7. Edit Barrier: Toggle between editing the label or the barrier mask.
  8. Pencil Size: Adjust the size of the brush and eraser tools.
  9. 3D Flood Fill Tool: Fill an area with the label based on similarity.
  10. STOP: Interrupt the ongoing flood fill operation.
  11. Info: Display information and usage tips.

- Sliders and Toggles (Bottom):
  1. Toggle Label: Show or hide the label overlay.
  2. Toggle Barrier: Show or hide the barrier overlay.
  3. Opacity: Adjust the transparency of the label and barrier overlays.
  4. Toggle Image: Show or hide the image data.
  5. Bucket Layer: Select the layer to adjust its specific flood fill threshold.
  6. Bucket Threshold: Set the threshold for the flood fill tool.
  7. Max Propagation: Limit the extent of the flood fill operation.

Usage Tips:
- Pouring Gold: The 3D flood fill algorithm labels contiguous areas based on voxel intensity and the set threshold.
    The gold does not propagate into the barrier.
- Navigation: Click and drag with the left mouse button to pan the image.
- Zoom: Use CTRL+Scroll to zoom in and out. Change the Z-axis slice with the mouse wheel.
- Editing Modes: Use the "Edit Barrier" toggle to switch between modifying the label and the barrier mask.
- Overlay Visibility: Use the toggle buttons to show or hide the label, barrier, and image data for easier editing.
- Tool Size: Use the "Pencil Size" slider to adjust the size of the brush and eraser.

Created by Dr. Giorgio Angelotti, Vesuvius Kintsugi is designed for efficient 3D voxel image labeling. Released under the MIT license.
"""
        # Insert the help text into the text widget and disable editing
        help_text_widget.insert("1.0", info_text)

    def update_max_propagation(self, val):
        self.max_propagation_steps = int(float(val))
        self.max_propagation_var.set(f"{self.max_propagation_steps}")
        self.update_log(f"Max Propagation Steps set to {self.max_propagation_steps}")

    def update_log(self, message):
        if self.log_text is not None:
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
        else:
            print(f"Log not ready: {message}")

    @staticmethod
    def create_tooltip(widget, text):
        # Implement a simple tooltip
        tooltip = tk.Toplevel(widget)
        tooltip.wm_overrideredirect(True)
        tooltip.wm_geometry("+0+0")
        tooltip.withdraw()

        label = tk.Label(tooltip, text=text, background="#FFFFE0", relief='solid', borderwidth=1, padx=1, pady=1)
        label.pack(ipadx=1)

        def enter(event):
            x = y = 0
            x, y, cx, cy = widget.bbox("insert")
            x += widget.winfo_rootx() + 25
            y += widget.winfo_rooty() + 20
            tooltip.wm_geometry(f"+{x}+{y}")
            tooltip.deiconify()

        def leave(event):
            tooltip.withdraw()

        widget.bind("<Enter>", enter)
        widget.bind("<Leave>", leave)

    def init_ui(self):
        self.root = tk.Tk()
        self.root.iconbitmap("./icons/favicon.ico")
        self.root.title("Vesuvius Kintsugi")

        # Use a ttk.Style object to configure style aspects of the application
        style = ttk.Style()
        style.configure('TButton', padding=5)  # Add padding around buttons
        style.configure('TFrame', padding=5)  # Add padding around frames

        # Create a toolbar frame at the top with some padding
        self.toolbar_frame = ttk.Frame(self.root, padding="5 5 5 5")
        self.toolbar_frame.pack(side=tk.TOP, fill=tk.X)

        # Create a drawing tools frame
        drawing_tools_frame = tk.Frame(self.toolbar_frame)
        drawing_tools_frame.pack(side=tk.LEFT, padx=5)

        # Load and set icons for buttons (icons need to be added)
        load_icon = PhotoImage(file='./icons/open-64.png') 
        save_icon = PhotoImage(file='./icons/save-64.png')
        prediction_icon = PhotoImage(file='./icons/prediction-64.png')
        undo_icon = PhotoImage(file='./icons/undo-64.png') 
        brush_icon = PhotoImage(file='./icons/brush-64.png')
        eraser_icon = PhotoImage(file='./icons/eraser-64.png')
        bucket_icon = PhotoImage(file='./icons/bucket-64.png')
        stop_icon = PhotoImage(file='./icons/stop-60.png')
        help_icon = PhotoImage(file='./icons/help-48.png')
        load_mask_icon = PhotoImage(file='./icons/ink-64.png')

        self.mode = tk.StringVar(value="bucket")

        # Add buttons with icons and tooltips to the toolbar frame
        load_button = ttk.Button(self.toolbar_frame, image=load_icon, command=self.load_data)
        load_button.image = load_icon
        load_button.pack(side=tk.LEFT, padx=2)
        self.create_tooltip(load_button, "Open Zarr 3D Image")

        load_mask_button = ttk.Button(self.toolbar_frame, image=load_mask_icon, command=self.load_mask)
        load_mask_button.image = load_mask_icon
        load_mask_button.pack(side=tk.LEFT, padx=2)
        self.create_tooltip(load_mask_button, "Load Ink Label")

        save_button = ttk.Button(self.toolbar_frame, image=save_icon, command=self.save_image)
        save_button.image = save_icon
        save_button.pack(side=tk.LEFT, padx=2)
        self.create_tooltip(save_button, "Save Zarr 3D Label")

        load_prediction = ttk.Button(self.toolbar_frame, image=prediction_icon, command=self.load_prediction)
        load_prediction.image = load_icon
        load_prediction.pack(side=tk.LEFT, padx=2)
        self.create_tooltip(load_prediction, "Load Ink Prediction")

        undo_button = ttk.Button(self.toolbar_frame, image=undo_icon, command=self.undo_last_action)
        undo_button.image = undo_icon
        undo_button.pack(side=tk.LEFT, padx=2)
        self.create_tooltip(undo_button, "Undo Last Action")

        # Brush tool button
        brush_button = ttk.Radiobutton(self.toolbar_frame, image=brush_icon, variable=self.mode, value="pencil")
        brush_button.image = brush_icon
        brush_button.pack(side=tk.LEFT, padx=2)
        self.create_tooltip(brush_button, "Brush Tool")

        # Eraser tool button
        eraser_button = ttk.Radiobutton(self.toolbar_frame, image=eraser_icon, variable=self.mode, value="eraser")
        eraser_button.image = eraser_icon
        eraser_button.pack(side=tk.LEFT, padx=2)
        self.create_tooltip(eraser_button, "Eraser Tool")

        self.editing_barrier_var = tk.BooleanVar(value=self.editing_barrier)
        toggle_editing_button = ttk.Checkbutton(self.toolbar_frame, text="Edit Barrier", command=self.toggle_editing_mode, variable=self.editing_barrier_var)
        toggle_editing_button.pack(side=tk.LEFT, padx=5)

        self.pencil_size_var = tk.StringVar(value="0")  # Default pencil size
        pencil_size_label = ttk.Label(self.toolbar_frame, text="Pencil Size:")
        pencil_size_label.pack(side=tk.LEFT, padx=(10, 2))  # Add some padding for spacing

        pencil_size_slider = ttk.Scale(self.toolbar_frame, from_=0, to=100, orient=tk.HORIZONTAL, command=self.update_pencil_size)
        pencil_size_slider.pack(side=tk.LEFT, padx=2)
        self.create_tooltip(pencil_size_slider, "Adjust Pencil Size")

        pencil_size_value_label = ttk.Label(self.toolbar_frame, textvariable=self.pencil_size_var)
        pencil_size_value_label.pack(side=tk.LEFT, padx=(0, 10))

        # Bucket tool button
        bucket_button = ttk.Radiobutton(self.toolbar_frame, image=bucket_icon, variable=self.mode, value="bucket")
        bucket_button.image = bucket_icon
        bucket_button.pack(side=tk.LEFT, padx=2)
        self.create_tooltip(bucket_button, "Flood Fill Tool")

        # Stop tool button
        stop_button = ttk.Button(self.toolbar_frame, image=stop_icon, command=self.stop_flood_fill)
        stop_button.image = stop_icon
        stop_button.pack(side=tk.LEFT, padx=2)
        self.create_tooltip(stop_button, "Stop Flood Fill")

        # Help button
        help_button = ttk.Button(self.toolbar_frame, image=help_icon, command=self.show_help)
        help_button.image = help_icon
        help_button.pack(side=tk.RIGHT, padx=2)
        self.create_tooltip(help_button, "Info")

        # Bucket Threshold Slider
        '''
        self.bucket_threshold_var = tk.StringVar(value="4")  # Default threshold
        bucket_threshold_label = ttk.Label(self.toolbar_frame, text="Bucket Threshold:")
        bucket_threshold_label.pack(side=tk.LEFT, padx=(10, 2))  # Add some padding for spacing

        self.bucket_threshold_slider = ttk.Scale(self.toolbar_frame, from_=0, to=100, orient=tk.HORIZONTAL, command=self.update_threshold_value)
        self.bucket_threshold_slider.pack(side=tk.LEFT, padx=2)
        self.create_tooltip(self.bucket_threshold_slider, "Adjust Bucket Threshold")

        bucket_threshold_value_label = ttk.Label(self.toolbar_frame, textvariable=self.bucket_threshold_var)
        bucket_threshold_value_label.pack(side=tk.LEFT, padx=(0, 10))
        '''
        # The canvas itself remains in the center
        self.canvas = tk.Canvas(self.root, width=400, height=400, bg='white')
        self.canvas.pack(fill='both', expand=True)

        self.z_slice_text = self.canvas.create_text(10, 10, anchor=tk.NW, text=f"Z-Slice: {self.z_index}", fill="red")

        self.cursor_pos_text = self.canvas.create_text(10, 30, anchor=tk.NW, text="Cursor Position: (0, 0)", fill="red")


        # Bind event handlers
        self.canvas.bind("<Motion>", self.update_pencil_cursor)
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_press)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<ButtonPress-3>", self.on_canvas_press)
        self.canvas.bind("<B3-Motion>", self.on_canvas_pencil_drag)
        self.canvas.bind("<ButtonRelease-3>", self.on_canvas_release)
        self.canvas.bind("<Button-3>", self.on_canvas_click)  # Assuming on_canvas_click is implemented
        self.canvas.bind("<MouseWheel>", self.scroll_or_zoom)  # Assuming scroll_or_zoom is implemented
        # On Linux, Button-4 is scroll up and Button-5 is scroll down
        self.canvas.bind("<Button-4>", self.scroll_or_zoom)
        self.canvas.bind("<Button-5>", self.scroll_or_zoom)

        # Variables for toggling states
        self.show_mask_var = tk.BooleanVar(value=self.show_mask)
        self.show_barrier_var = tk.BooleanVar(value=self.show_barrier)
        self.show_image_var = tk.BooleanVar(value=self.show_image)
        self.show_prediction_var = tk.BooleanVar(value=self.show_prediction)

        # Create a frame to hold the toggle buttons
        toggle_frame = tk.Frame(self.root)
        toggle_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=2)

        # Create toggle buttons for mask and image visibility
        toggle_mask_button = ttk.Checkbutton(toggle_frame, text="Label", command=self.toggle_mask, variable=self.show_mask_var)
        toggle_mask_button.pack(side=tk.LEFT, padx=5, anchor='s')

        toggle_barrier_button = ttk.Checkbutton(toggle_frame, text="Barrier", command=self.toggle_barrier, variable=self.show_barrier_var)
        toggle_barrier_button.pack(side=tk.LEFT, padx=5, anchor='s')

        toggle_prediction_button = ttk.Checkbutton(toggle_frame, text="Prediction", command=self.toggle_prediction, variable=self.show_prediction_var)
        toggle_prediction_button.pack(side=tk.LEFT, padx=5, anchor='s')

        # Slider for adjusting the alpha (opacity)
        self.alpha_var = tk.IntVar(value=self.overlay_alpha)
        alpha_label = ttk.Label(toggle_frame, text="Opacity:")
        alpha_label.pack(side=tk.LEFT, padx=5, anchor='s')
        alpha_slider = ttk.Scale(toggle_frame, from_=0, to=255, orient=tk.HORIZONTAL, command=self.update_alpha)
        alpha_slider.set(self.overlay_alpha)  # Set the default position of the slider
        alpha_slider.pack(side=tk.LEFT, padx=5, anchor='s')
        self.create_tooltip(alpha_slider, "Adjust Overlay Opacity")

        toggle_image_button = ttk.Checkbutton(toggle_frame, text="Toggle Image", command=self.toggle_image, variable=self.show_image_var)
        toggle_image_button.pack(side=tk.LEFT, padx=5, anchor='s')

        # Create a frame specifically for the sliders
        slider_frame = ttk.Frame(toggle_frame)
        slider_frame.pack(side=tk.RIGHT, padx=5)

        # Bucket Layer Slider
        self.bucket_layer_var = tk.StringVar(value="0")
        bucket_layer_label = ttk.Label(slider_frame, text="Bucket Layer:")
        bucket_layer_label.pack(side=tk.LEFT, padx=(10, 2))

        self.bucket_layer_slider = ttk.Scale(slider_frame, from_=0, to=0, orient=tk.HORIZONTAL, command=self.update_threshold_layer)
        self.bucket_layer_slider.pack(side=tk.LEFT, padx=2)
        self.create_tooltip(self.bucket_layer_slider, "Adjust Bucket Layer")

        bucket_layer_value_label = ttk.Label(slider_frame, textvariable=self.bucket_layer_var)
        bucket_layer_value_label.pack(side=tk.LEFT, padx=(0, 10))

        # Bucket Threshold Slider
        self.bucket_threshold_var = tk.StringVar(value="4")
        bucket_threshold_label = ttk.Label(slider_frame, text="Bucket Threshold:")
        bucket_threshold_label.pack(side=tk.LEFT, padx=(10, 2))

        self.bucket_threshold_slider = ttk.Scale(slider_frame, from_=0, to=100, orient=tk.HORIZONTAL, command=self.update_threshold_value)
        self.bucket_threshold_slider.pack(side=tk.LEFT, padx=2)
        self.create_tooltip(self.bucket_threshold_slider, "Adjust Bucket Threshold")

        bucket_threshold_value_label = ttk.Label(slider_frame, textvariable=self.bucket_threshold_var)
        bucket_threshold_value_label.pack(side=tk.LEFT, padx=(0, 10))

        # Max Propagation Slider
        self.max_propagation_var = tk.IntVar(value=self.max_propagation_steps)
        max_propagation_label = ttk.Label(slider_frame, text="Max Propagation:")
        max_propagation_label.pack(side=tk.LEFT, padx=(10, 2))

        max_propagation_slider = ttk.Scale(slider_frame, from_=1, to=500, orient=tk.HORIZONTAL, command=self.update_max_propagation)
        max_propagation_slider.set(self.max_propagation_steps)
        max_propagation_slider.pack(side=tk.LEFT, padx=2)
        self.create_tooltip(max_propagation_slider, "Adjust Max Propagation Steps for Flood Fill")

        max_propagation_value_label = ttk.Label(slider_frame, textvariable=self.max_propagation_var)
        max_propagation_value_label.pack(side=tk.LEFT, padx=(0, 10))

        # Create a frame for the log text area and scrollbar
        log_frame = tk.Frame(self.root)
        log_frame.pack(side=tk.BOTTOM, fill=tk.X)

        # Create the log text widget
        self.log_text = tk.Text(log_frame, height=4, width=50)
        self.log_text.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Create the scrollbar and associate it with the log text widget
        log_scrollbar = tk.Scrollbar(log_frame, command=self.log_text.yview)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text['yscrollcommand'] = log_scrollbar.set

        self.root.mainloop()

if __name__ == "__main__":
    editor = VesuviusKintsugi()
