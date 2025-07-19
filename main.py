import tkinter as tk
from tkinter import font
from tkinter import ttk
import requests
from datetime import datetime
from PIL import Image, ImageTk
import io
import re
import threading
import time
import webbrowser
from queue import Queue
from playsound import playsound


class GroupMePushClient:
    def __init__(self, access_token, user_id, message_queue, status_callback=None):
        self.access_token = access_token
        self.user_id = user_id
        self.message_queue = message_queue
        self.status_callback = status_callback
        self.client_id = None
        self.faye_url = "https://push.groupme.com/faye"
        self.session = requests.Session()
        self.running = False
        self.message_id_counter = 0
        self.reconnect_delay = 5  # seconds

    def _send_faye_request(self, messages):
        headers = {"Content-Type": "application/json"}
        try:
            response = self.session.post(self.faye_url, headers=headers, json=messages)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Faye request failed: {e}")
            if self.status_callback:
                self.status_callback("disconnected")
            self.client_id = None  # Invalidate client_id to force re-handshake
            return None

    def handshake(self):
        self.message_id_counter += 1
        handshake_message = {
            "channel": "/meta/handshake",
            "version": "1.0",
            "supportedConnectionTypes": ["long-polling"],
            "id": str(self.message_id_counter),
        }
        response = self._send_faye_request([handshake_message])
        if response and response[0].get("successful"):
            self.client_id = response[0].get("clientId")
            print(f"Faye handshake successful. Client ID: {self.client_id}")
            return True
        return False

    def subscribe_user_channel(self):
        if not self.client_id:
            print("Cannot subscribe: no client ID (perform handshake first).")
            return False

        self.message_id_counter += 1
        subscribe_message = {
            "channel": "/meta/subscribe",
            "clientId": self.client_id,
            "subscription": f"/user/{self.user_id}",
            "id": str(self.message_id_counter),
            "ext": {"access_token": self.access_token, "timestamp": int(time.time())},
        }
        response = self._send_faye_request([subscribe_message])
        if response and response[0].get("successful"):
            print(f"Subscribed to user channel /user/{self.user_id}")
            return True
        return False

    def connect(self):
        while self.running:
            if not self.client_id:
                print("Attempting to re-establish Faye connection...")
                if self.status_callback:
                    self.status_callback("connecting")
                if self.handshake() and self.subscribe_user_channel():
                    print("Faye connection re-established.")
                    if self.status_callback:
                        self.status_callback("connected")
                else:
                    print(
                        f"Failed to re-establish Faye connection. Retrying in {self.reconnect_delay} seconds..."
                    )
                    if self.status_callback:
                        self.status_callback("disconnected")
                    time.sleep(self.reconnect_delay)
                    continue  # Skip to next iteration to retry handshake

            self.message_id_counter += 1
            connect_message = {
                "channel": "/meta/connect",
                "clientId": self.client_id,
                "connectionType": "long-polling",
                "id": str(self.message_id_counter),
            }
            response = self._send_faye_request([connect_message])
            if response:
                for msg in response:
                    if msg.get("channel") == f"/user/{self.user_id}" and msg.get(
                        "data"
                    ):
                        self.message_queue.put(msg["data"])
                    elif msg.get("channel") == "/meta/connect" and not msg.get(
                        "successful"
                    ):
                        print(
                            "Faye connect message returned unsuccessful. Reconnecting..."
                        )
                        self.client_id = None  # Force re-handshake
                        time.sleep(self.reconnect_delay)
                        break  # Exit inner loop to start reconnection process
            time.sleep(1)  # Poll every second

    def start(self):
        self.running = True
        threading.Thread(target=self.connect, daemon=True).start()

    def stop(self):
        self.running = False
        print("GroupMe push client stopped.")


class HexChatUI(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.master.title("GxChat")
        self.pack(fill=tk.BOTH, expand=True)
        self.configure(bg="#2a2a2a")
        self.groups = []
        self.current_group_id = None
        self.current_username = "User1"  # Default username
        self.current_nickname_in_group = None
        self.current_channel_name = ""  # Default channel name
        self.current_user_id = None
        self.current_members = []
        self.chat_history_image_references = []  # To prevent images from being garbage collected
        self.message_queue = Queue()
        self.groupme_push_client = None  # Will be initialized after fetching user ID
        self.polling_job = None
        self.is_polling = False
        self.displayed_message_ids = set()
        self.messages_cache = []
        self.create_widgets()
        self.after(100, self.process_message_queue)  # Start processing queue
        self.show_login_view()

    def create_widgets(self):
        # Main frame
        main_frame = tk.Frame(self, bg="#2a2a2a")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Style for PanedWindow
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TPanedWindow", background="#2a2a2a")
        style.configure(
            "TPanedWindow.Sash",
            background="#2a2a2a",
            bordercolor="#2a2a2a",
            relief=tk.FLAT,
        )
        style.map("TPanedWindow.Sash", background=[("!disabled", "#2a2a2a")])

        # Top-level PanedWindow for resizable columns
        self.main_paned_window = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)

        # Bottom frame for user info and input
        self.bottom_frame = tk.Frame(main_frame, bg="#2a2a2a")

        # Pack containers in the correct order for proper resizing
        self.bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(5, 0))
        self.main_paned_window.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Channel list (left pane)
        channel_list_frame = tk.Frame(self.main_paned_window, bg="#3c3c3c")
        channel_list_label = tk.Label(
            channel_list_frame,
            text="Channels",
            bg="#3c3c3c",
            fg="white",
            font=("Courier", 14, "bold"),
        )
        channel_list_label.pack(pady=5, padx=5, anchor="w")
        self.channel_list = tk.Listbox(
            channel_list_frame,
            bg="#3c3c3c",
            fg="white",
            selectbackground="#555555",
            selectforeground="white",
            highlightthickness=0,
            borderwidth=0,
            font=("Courier", 12),
        )
        self.channel_list.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))
        self.channel_list.bind("<<ListboxSelect>>", self.on_channel_select)
        self.main_paned_window.add(channel_list_frame, weight=0)

        # Create a new paned window for the chat and user list.
        chat_user_paned_window = ttk.PanedWindow(
            self.main_paned_window, orient=tk.HORIZONTAL
        )
        self.main_paned_window.add(chat_user_paned_window, weight=1)

        # Chat history and description container (middle pane)
        chat_description_history_frame = tk.Frame(chat_user_paned_window, bg="#1e1e1e")
        chat_user_paned_window.add(chat_description_history_frame, weight=1)

        # Channel Description Entry (read-only appearance)
        self.channel_description_entry = tk.Entry(
            chat_description_history_frame,
            bg="#3c3c3c",
            fg="white",
            insertbackground="white",
            font=("Courier", 12),
            borderwidth=0,
            highlightthickness=1,
            highlightcolor="#555555",
            highlightbackground="#444444",
            state="normal",  # Allow cursor and selection
            validate="all",
            validatecommand=(
                self.register(self.validate_readonly_entry),
                "%P",
            ),  # %P is the new value of the entry
        )
        self.channel_description_entry.pack(fill=tk.X, padx=5, pady=(0, 5))

        # Chat history (below description)
        self.chat_history = tk.Text(
            chat_description_history_frame,  # Pack into the new container frame
            wrap=tk.WORD,
            state=tk.DISABLED,
            bg="#1e1e1e",
            fg="white",
            font=("Courier", 12),
            borderwidth=0,
            highlightthickness=0,
        )
        self.chat_history.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # User list (right pane)
        user_list_frame = tk.Frame(chat_user_paned_window, bg="#1e1e1e")
        self.user_list = tk.Listbox(
            user_list_frame,
            bg="#1e1e1e",
            fg="#a9a9a9",
            highlightthickness=0,
            borderwidth=0,
            font=("Courier", 12),
        )
        self.user_list.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        chat_user_paned_window.add(user_list_frame, weight=0)

        # User info and input field
        self.online_indicator = tk.Canvas(
            self.bottom_frame, width=10, height=10, bg="#2a2a2a", highlightthickness=0
        )
        self.online_indicator.create_oval(
            0, 0, 10, 10, fill="#00ff00", outline="#00ff00"
        )  # Green circle
        self.online_indicator.pack(side=tk.LEFT, padx=(5, 2), pady=(0, 5))

        self.user_info_label = tk.Label(
            self.bottom_frame,
            text=self.current_username,
            bg="#2a2a2a",
            fg="white",
            font=("Courier", 14, "bold"),
        )
        self.user_info_label.pack(side=tk.LEFT, padx=(0, 5), pady=(0, 5))

        self.chat_input = tk.Entry(
            self.bottom_frame,
            bg="#3c3c3c",
            fg="white",
            insertbackground="white",
            font=("Courier", 12),
            borderwidth=0,
            highlightthickness=1,
            highlightcolor="#555555",
            highlightbackground="#444444",
        )
        self.chat_input.pack(fill=tk.X, expand=True, padx=(0, 5), pady=(0, 5), ipady=4)
        self.chat_input.bind("<Return>", self.send_message)

        # Login Frame
        self.login_frame = tk.Frame(self, bg="#2a2a2a")
        self.login_frame.pack(fill=tk.BOTH, expand=True)

        self.welcome_label = tk.Label(
            self.login_frame,
            text="Welcome to GxChat!\nPlease log in to continue.",
            bg="#2a2a2a",
            fg="white",
            font=("Courier", 16, "bold"),
            wraplength=400,
            justify=tk.CENTER,
        )
        self.welcome_label.pack(pady=(100, 20))

        self.login_button = tk.Button(
            self.login_frame,
            text="Login with GroupMe",
            bg="#4CAF50",
            fg="black",
            font=("Courier", 12, "bold"),
            command=self.open_oauth_url,
        )
        self.login_button.pack(pady=20)

    def open_oauth_url(self):
        client_id = "lSSJQfxNbjkJLO2JVv7MdMGcTbitGX1VP5rkJS0S8lkfTVmC"
        auth_url = f"https://oauth.groupme.com/oauth/authorize?client_id={client_id}"
        webbrowser.open_new(auth_url)

    def show_login_view(self):
        self.main_paned_window.pack_forget()
        self.bottom_frame.pack_forget()
        self.login_frame.pack(fill=tk.BOTH, expand=True)
        self.check_auth_status()

    def check_auth_status(self):
        try:
            response = requests.get("http://127.0.0.1:3000/token")
            response.raise_for_status()
            token_data = response.json()
            if token_data.get("token"):
                self.show_main_view()
                return
        except requests.exceptions.RequestException:
            pass  # Ignore connection errors, we'll retry
        self.after(1000, self.check_auth_status)

    def show_main_view(self):
        self.login_frame.pack_forget()
        self.main_paned_window.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(5, 0))
        self.fetch_current_user()
        self.fetch_groups()
        self.after(200, self.start_faye_client)

    def fetch_current_user(self):
        try:
            response = requests.get("http://127.0.0.1:3000/user/me")
            response.raise_for_status()
            user_data = response.json()
            self.current_username = user_data.get("name", "User1")
            self.current_user_id = user_data.get("id")
            self.user_info_label.config(text=self.current_username)
            self.update_window_title()

            # Initialize GroupMePushClient after fetching user ID, but don't start it yet
            if self.current_user_id and not self.groupme_push_client:
                token_response = requests.get("http://127.0.0.1:3000/token")
                token_response.raise_for_status()
                access_token = token_response.json().get("token")
                self.groupme_push_client = GroupMePushClient(
                    access_token,
                    self.current_user_id,
                    self.message_queue,
                    self.update_online_indicator,
                )
        except requests.exceptions.RequestException as e:
            self.add_message("System", f"Error fetching current user: {e}")

    def update_window_title(self):
        title = f"GxChat: {self.current_username}"
        if self.current_channel_name:
            title += f" @ #{self.current_channel_name}"
        self.master.title(title)

    def fetch_groups(self):
        self.fetch_current_user()  # Fetch user info when refreshing groups
        try:
            response = requests.get("http://127.0.0.1:3000/groups")
            response.raise_for_status()
            self.groups = response.json()
            self.update_channel_list()
        except requests.exceptions.RequestException as e:
            self.add_message("System", f"Error fetching groups: {e}")

    def update_channel_list(self):
        self.channel_list.delete(0, tk.END)
        for group in self.groups:
            self.channel_list.insert(tk.END, f"#{group['name']}")
        if self.groups and not self.current_group_id:
            self.channel_list.selection_set(0)  # Select the first item
            self.on_channel_select(None)  # Manually trigger the selection handler

    def on_channel_select(self, event):
        self.stop_polling()  # Stop polling for the old channel
        selection = self.channel_list.curselection()
        if selection:
            index = selection[0]
            group_id = self.groups[index][
                "id"
            ]  # Get ID from current (possibly stale) list

            # Clear previous channel state
            self.chat_history.config(state=tk.NORMAL)
            self.chat_history.delete(1.0, tk.END)
            self.chat_history.config(state=tk.DISABLED)
            self.chat_history_image_references.clear()
            self.displayed_message_ids.clear()
            self.messages_cache.clear()

            try:
                # Fetch the latest list of all groups to get fresh member data
                response = requests.get("http://127.0.0.1:3000/groups")
                response.raise_for_status()
                all_groups = response.json()
                self.groups = all_groups  # Update the stored list of groups

                # Find the selected group in the fresh list
                group = next((g for g in all_groups if g["id"] == group_id), None)

                if group:
                    self.current_group_id = group["id"]
                    self.current_channel_name = group["name"]
                    self.current_members = group["members"]

                    # Find and set the user's nickname for the current group
                    self.current_nickname_in_group = self.current_username
                    for member in self.current_members:
                        if member.get("user_id") == self.current_user_id:
                            self.current_nickname_in_group = member.get("nickname")
                            break

                    self.update_user_list(group["members"])
                    self.fetch_messages(self.current_group_id, initial_load=True)
                    self.update_window_title()
                    self.update_channel_description_entry(group.get("description", ""))

                    # Ensure push client is running
                    if (
                        self.groupme_push_client
                        and not self.groupme_push_client.running
                    ):
                        self.groupme_push_client.start()

                    self.start_polling()  # Start polling for the new channel
                else:
                    self.add_message(
                        "System",
                        f"Could not find details for group {group_id} after refresh.",
                    )

            except requests.exceptions.RequestException as e:
                self.add_message("System", f"Error fetching group list: {e}")

    def start_polling(self):
        if not self.is_polling and self.current_group_id:
            self.is_polling = True
            self.poll_messages()

    def stop_polling(self):
        if self.polling_job:
            self.after_cancel(self.polling_job)
            self.polling_job = None
        self.is_polling = False

    def poll_messages(self):
        if self.is_polling and self.current_group_id:
            self.fetch_messages(self.current_group_id)
            self.polling_job = self.after(
                5000, self.poll_messages
            )  # Poll every 5 seconds

    def validate_readonly_entry(self, new_value):
        # Always return False to prevent any changes to the entry widget
        return False

    def update_channel_description_entry(self, description):
        # Temporarily disable validation to allow programmatic update
        self.channel_description_entry.config(validate="none")
        self.channel_description_entry.delete(0, tk.END)
        self.channel_description_entry.insert(0, description)
        # Re-enable validation
        self.channel_description_entry.config(validate="all")

    def update_user_list(self, members):
        self.user_list.delete(0, tk.END)
        for member in members:
            self.user_list.insert(tk.END, member["nickname"])

    def fetch_messages(self, group_id, initial_load=False):
        try:
            response = requests.get(f"http://127.0.0.1:3000/groups/{group_id}/messages")
            response.raise_for_status()
            messages = response.json()

            if messages != self.messages_cache:
                self.messages_cache = messages  # Update cache

                # Preserve scroll position and check if user is at the bottom
                scroll_position = self.chat_history.yview()
                is_at_bottom = scroll_position[1] > 0.9

                # Rebuild chat history
                self.chat_history.config(state=tk.NORMAL)
                self.chat_history.delete(1.0, tk.END)
                self.chat_history_image_references.clear()

                for message in reversed(messages):
                    self.add_new_message(message, from_history=True)

                self.chat_history.config(state=tk.DISABLED)

                # Restore scroll position or scroll to bottom
                if initial_load or is_at_bottom:
                    self.chat_history.see(tk.END)
                else:
                    self.chat_history.yview_moveto(scroll_position[0])

        except requests.exceptions.RequestException as e:
            self.add_message("System", f"Error fetching messages: {e}")

    def add_new_message(self, message, from_history=False):
        message_id = message.get("id")
        if not from_history and message_id in self.displayed_message_ids:
            return  # Don't add duplicate real-time messages

        user = message.get("name", "Unknown")
        text = message.get("text", "")
        created_at = datetime.fromtimestamp(message.get("created_at", 0))

        # Check for image attachments
        image_url = None
        attachments = message.get("attachments", [])
        for attachment in attachments:
            if attachment.get("type") == "image":
                image_url = attachment.get("url")
                break

        if image_url:
            self.add_message(user, "", created_at)
            self.add_image_to_chat(image_url)
        elif text:
            self.add_message(user, text, created_at)

        # Display likes
        favorited_by = message.get("favorited_by", [])
        if favorited_by:
            liker_names = [self.get_user_name(liker_id) for liker_id in favorited_by]
            likes_message = f"  Liked by: {', '.join(liker_names)}"
            self.add_message("System", likes_message, None, is_like=True)

        self.displayed_message_ids.add(message_id)  # Mark message as displayed

        if not from_history:
            # Check for mention and play the appropriate sound
            if f"@{self.current_nickname_in_group}" in text:
                self.play_mention_sound()
            else:
                self.play_new_message_sound()

    def get_user_name(self, user_id):
        for member in self.current_members:
            if member["user_id"] == user_id:
                return member["nickname"]
        return "Unknown User"

    def add_image_to_chat(self, image_url, max_size=(300, 300)):
        try:
            response = requests.get(image_url, stream=True)
            response.raise_for_status()
            image_data = response.content
            image = Image.open(io.BytesIO(image_data))
            image.thumbnail(max_size, Image.Resampling.LANCZOS)

            # Ensure image is in RGBA mode for PhotoImage compatibility
            image = image.convert("RGBA")

            # Explicitly load the image data to ensure it's fully processed
            image.load()

            photo = ImageTk.PhotoImage(image)

            self.chat_history.config(state=tk.NORMAL)
            self.chat_history.image_create(tk.END, image=photo)
            self.chat_history.insert(tk.END, "\n")  # Add a newline after the image
            self.chat_history.config(state=tk.DISABLED)

            # Auto-scroll only if the user is near the bottom
            scroll_position = self.chat_history.yview()[1]
            if scroll_position > 0.9:
                self.chat_history.see(tk.END)

            self.chat_history_image_references.append(photo)  # Keep a reference
        except Exception as e:
            self.add_message("System", f"Error loading image from {image_url}: {e}")

    def send_message(self, event):
        message_text = self.chat_input.get()
        if message_text and self.current_group_id:
            try:
                payload = {"text": message_text}
                response = requests.post(
                    f"http://127.0.0.1:3000/groups/{self.current_group_id}/messages",
                    json=payload,
                )
                response.raise_for_status()
                self.chat_input.delete(0, tk.END)
                # Display sent message immediately
                # self.add_message(nickname, message_text) # Display sent message immediately
                # self.fetch_messages(self.current_group_id) # No need to re-fetch all messages
            except requests.exceptions.RequestException as e:
                self.add_message("System", f"Error sending message: {e}")

    def add_message(self, user, message, timestamp=None, is_like=False):
        self.chat_history.config(state=tk.NORMAL)

        if is_like:
            self.chat_history.tag_configure(
                "like_message", foreground="#ff69b4"
            )  # Pink for likes
            self.chat_history.insert(tk.END, f"{message}\n", "like_message")
        else:
            # User tag
            user_font = font.Font(self.chat_history, self.chat_history.cget("font"))
            user_font.configure(weight="bold")
            self.chat_history.tag_configure(
                "user_tag", font=user_font, foreground="#87ceeb"
            )

            # Timestamp
            if timestamp is None:
                timestamp = datetime.now()
            timestamp_str = timestamp.strftime("%H:%M")
            self.chat_history.tag_configure("timestamp", foreground="#a9a9a9")

            self.chat_history.insert(tk.END, f"[{timestamp_str}] ", "timestamp")
            self.chat_history.insert(tk.END, f"{user}: ", "user_tag")

            # Find and tag hyperlinks
            url_pattern = re.compile(r"https?://\S+")
            matches = url_pattern.finditer(message)
            last_end = 0
            for match in matches:
                start, end = match.span()
                self.chat_history.insert(tk.END, message[last_end:start])
                # Insert the hyperlink with a tag
                hyperlink = message[start:end]
                self.chat_history.insert(
                    tk.END, hyperlink, ("hyperlink", f"hyperlink-{hyperlink}")
                )
                last_end = end
            self.chat_history.insert(tk.END, message[last_end:] + "\n")

            self.chat_history.tag_configure(
                "hyperlink", foreground="#00BFFF", underline=True
            )
            self.chat_history.tag_bind(
                "hyperlink", "<Button-1>", self.on_hyperlink_click
            )
            self.chat_history.tag_bind("hyperlink", "<Enter>", self.on_hyperlink_enter)
            self.chat_history.tag_bind("hyperlink", "<Leave>", self.on_hyperlink_leave)

        self.chat_history.config(state=tk.DISABLED)

        # Auto-scroll only if the user is near the bottom
        scroll_position = self.chat_history.yview()[1]
        if scroll_position > 0.9:
            self.chat_history.see(tk.END)

    def on_hyperlink_click(self, event):
        # Get the tag at the clicked position
        tags = self.chat_history.tag_names(tk.CURRENT)
        for tag in tags:
            if tag.startswith("hyperlink-"):
                url = tag.replace("hyperlink-", "", 1)
                webbrowser.open_new(url)
                break

    def on_hyperlink_enter(self, event):
        self.chat_history.config(cursor="hand2")

    def on_hyperlink_leave(self, event):
        self.chat_history.config(cursor="")

    def play_mention_sound(self):
        print("play_mention_sound() called.")
        try:
            threading.Thread(
                target=playsound, args=("sounds/mentioned.mp3",), daemon=True
            ).start()
        except Exception as e:
            print(f"Error playing sound: {e}")

    def play_new_message_sound(self):
        try:
            threading.Thread(
                target=playsound, args=("sounds/ping.mp3",), daemon=True
            ).start()
        except Exception as e:
            print(f"Error playing sound: {e}")

    def process_message_queue(self):
        try:
            while not self.message_queue.empty():
                message_data = self.message_queue.get_nowait()
                if message_data.get("type") == "line.create":
                    message = message_data.get("subject")
                    if message and message.get("group_id") == self.current_group_id:
                        # Add to message cache
                        self.messages_cache.append(message)
                        # Add to UI
                        self.add_new_message(message)
        finally:
            self.after(100, self.process_message_queue)

    def start_faye_client(self):
        if self.groupme_push_client and not self.groupme_push_client.running:
            self.groupme_push_client.start()

    def update_online_indicator(self, status):
        # Schedule the actual GUI update to run on the main thread
        self.master.after(0, lambda: self._update_online_indicator_gui(status))

    def _update_online_indicator_gui(self, status):
        color = "#00ff00"  # Green for connected
        if status == "disconnected":
            color = "#ff0000"  # Red for disconnected
        elif status == "connecting":
            color = "#ffa500"  # Orange for connecting
        self.online_indicator.itemconfig(
            self.online_indicator.find_all()[0], fill=color, outline=color
        )


if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("800x600")
    app = HexChatUI(master=root)
    app.mainloop()
