import tkinter as tk
from tkinter import font
import requests
from datetime import datetime
from PIL import Image, ImageTk
import io
import threading
import json
import time
from queue import Queue

class GroupMePushClient:
    def __init__(self, access_token, user_id, message_queue):
        self.access_token = access_token
        self.user_id = user_id
        self.message_queue = message_queue
        self.client_id = None
        self.faye_url = "https://push.groupme.com/faye"
        self.session = requests.Session()
        self.running = False
        self.message_id_counter = 0

    def _send_faye_request(self, messages):
        headers = {"Content-Type": "application/json"}
        try:
            response = self.session.post(self.faye_url, headers=headers, json=messages)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Faye request failed: {e}")
            return None

    def handshake(self):
        self.message_id_counter += 1
        handshake_message = {
            "channel": "/meta/handshake",
            "version": "1.0",
            "supportedConnectionTypes": ["long-polling"],
            "id": str(self.message_id_counter)
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
            "ext": {
                "access_token": self.access_token,
                "timestamp": int(time.time())
            }
        }
        response = self._send_faye_request([subscribe_message])
        if response and response[0].get("successful"):
            print(f"Subscribed to user channel /user/{self.user_id}")
            return True
        return False

    def connect(self):
        if not self.client_id:
            print("Cannot connect: no client ID (perform handshake first).")
            return

        self.message_id_counter += 1
        connect_message = {
            "channel": "/meta/connect",
            "clientId": self.client_id,
            "connectionType": "long-polling",
            "id": str(self.message_id_counter)
        }
        while self.running:
            response = self._send_faye_request([connect_message])
            if response:
                for msg in response:
                    if msg.get("channel") == f"/user/{self.user_id}" and msg.get("data"):
                        # Process message data
                        self.message_queue.put(msg["data"])
            time.sleep(1) # Poll every second

    def start(self):
        self.running = True
        if self.handshake() and self.subscribe_user_channel():
            threading.Thread(target=self.connect, daemon=True).start()
        else:
            print("Failed to start GroupMe push client.")

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
        self.current_username = "User1" # Default username
        self.current_user_id = None
        self.current_members = []
        self.chat_history_image_references = [] # To prevent images from being garbage collected
        self.message_queue = Queue()
        self.groupme_push_client = None # Will be initialized after fetching user ID
        self.create_widgets()
        self.fetch_current_user()
        self.after(100, self.process_message_queue) # Start processing queue

    def create_widgets(self):
        # Main frame
        main_frame = tk.Frame(self, bg="#2a2a2a")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Top-level PanedWindow for resizable columns
        main_paned_window = tk.PanedWindow(main_frame, orient=tk.HORIZONTAL, sashwidth=5, bg="#2a2a2a")
        main_paned_window.pack(fill=tk.BOTH, expand=True)

        # Channel list (left pane)
        channel_list_frame = tk.Frame(main_paned_window, bg="#3c3c3c")
        channel_list_label = tk.Label(channel_list_frame, text="Channels", bg="#3c3c3c", fg="white", font=("Courier", 14, "bold"))
        channel_list_label.pack(pady=5, padx=5, anchor='w')
        self.channel_list = tk.Listbox(
            channel_list_frame,
            bg="#3c3c3c",
            fg="white",
            selectbackground="#555555",
            selectforeground="white",
            highlightthickness=0,
            borderwidth=0,
            font=("Courier", 14)
        )
        self.channel_list.pack(fill=tk.Y, expand=True, padx=5, pady=(0,5))
        self.channel_list.bind("<<ListboxSelect>>", self.on_channel_select)
        main_paned_window.add(channel_list_frame, width=200, minsize=100)

        # Create a new paned window for the chat and user list.
        chat_user_paned_window = tk.PanedWindow(main_paned_window, orient=tk.HORIZONTAL, sashwidth=5, bg="#2a2a2a")
        main_paned_window.add(chat_user_paned_window)

        # Chat history (middle pane)
        chat_history_frame = tk.Frame(chat_user_paned_window, bg="#1e1e1e")
        self.chat_history = tk.Text(
            chat_history_frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
            bg="#1e1e1e",
            fg="white",
            font=("Courier", 14),
            borderwidth=0,
            highlightthickness=0
        )
        self.chat_history.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        chat_user_paned_window.add(chat_history_frame, width=400, minsize=200)

        # User list (right pane)
        user_list_frame = tk.Frame(chat_user_paned_window, bg="#1e1e1e")
        self.user_list = tk.Listbox(
            user_list_frame,
            bg="#1e1e1e",
            fg="#a9a9a9",
            highlightthickness=0,
            borderwidth=0,
            font=("Courier", 14)
        )
        self.user_list.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        chat_user_paned_window.add(user_list_frame, width=200, minsize=100)

        # Bottom frame for user info and input
        bottom_frame = tk.Frame(main_frame, bg="#2a2a2a")
        bottom_frame.pack(fill=tk.X)

        # User info and input field
        self.user_info_label = tk.Label(bottom_frame, text=self.current_username, bg="#2a2a2a", fg="white", font=("Courier", 14, "bold"))
        self.user_info_label.pack(side=tk.LEFT, padx=5, pady=(0,5))

        self.chat_input = tk.Entry(
            bottom_frame,
            bg="#3c3c3c",
            fg="white",
            insertbackground='white',
            font=("Courier", 14),
            borderwidth=0,
            highlightthickness=1,
            highlightcolor="#555555",
            highlightbackground="#444444"
        )
        self.chat_input.pack(fill=tk.X, expand=True, padx=(0,5), pady=(0,5), ipady=4)
        self.chat_input.bind("<Return>", self.send_message)

        # Refresh button
        refresh_button = tk.Button(bottom_frame, text="Refresh", command=self.fetch_groups, bg="#3c3c3c", fg="white", borderwidth=0, highlightthickness=0)
        refresh_button.pack(side=tk.RIGHT, padx=5, pady=5)

    def fetch_current_user(self):
        try:
            response = requests.get("http://127.0.0.1:3000/user/me")
            response.raise_for_status()
            user_data = response.json()
            self.current_username = user_data.get('name', "User1")
            self.current_user_id = user_data.get('id')
            self.user_info_label.config(text=self.current_username)

            # Initialize and start GroupMePushClient after fetching user ID
            if self.current_user_id and not self.groupme_push_client:
                # TODO: Replace with actual access token retrieval
                access_token = "***REMOVED***" # Placeholder
                self.groupme_push_client = GroupMePushClient(access_token, self.current_user_id, self.message_queue)
                self.groupme_push_client.start()
        except requests.exceptions.RequestException as e:
            self.add_message("System", f"Error fetching current user: {e}")

    def fetch_groups(self):
        self.fetch_current_user() # Fetch user info when refreshing groups
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
            self.channel_list.insert(tk.END, f"  #{group['name']}")

    def on_channel_select(self, event):
        selection = event.widget.curselection()
        if selection:
            index = selection[0]
            group = self.groups[index]
            self.current_group_id = group['id']
            self.current_members = group['members']
            self.update_user_list(group['members'])
            self.fetch_messages(self.current_group_id)

            # Ensure push client is running
            if self.groupme_push_client and not self.groupme_push_client.running:
                self.groupme_push_client.start()

    def update_user_list(self, members):
        self.user_list.delete(0, tk.END)
        for member in members:
            self.user_list.insert(tk.END, member['nickname'])

    def fetch_messages(self, group_id):
        self.chat_history.config(state=tk.NORMAL)
        self.chat_history.delete(1.0, tk.END)
        self.chat_history_image_references.clear() # Clear image references for new chat
        self.chat_history.config(state=tk.DISABLED)
        try:
            response = requests.get(f"http://127.0.0.1:3000/groups/{group_id}/messages")
            response.raise_for_status()
            messages = response.json()
            for message in reversed(messages):
                user = message.get('name', 'Unknown')
                text = message.get('text', '')
                created_at = datetime.fromtimestamp(message.get('created_at', 0))
                
                # Check for image attachments
                image_url = None
                attachments = message.get('attachments', [])
                for attachment in attachments:
                    if attachment.get('type') == 'image':
                        image_url = attachment.get('url')
                        break

                if image_url:
                    self.add_message(user, "", created_at) # Add timestamp and user
                    self.add_image_to_chat(image_url) # Add image
                elif text:
                    self.add_message(user, text, created_at)

                # Display likes
                favorited_by = message.get('favorited_by', [])
                if favorited_by:
                    liker_names = [self.get_user_name(liker_id) for liker_id in favorited_by]
                    likes_message = f"  Liked by: {', '.join(liker_names)}"
                    self.add_message("System", likes_message, None, is_like=True)

        except requests.exceptions.RequestException as e:
            self.add_message("System", f"Error fetching messages: {e}")

    def get_user_name(self, user_id):
        for member in self.current_members:
            if member['user_id'] == user_id:
                return member['nickname']
        return "Unknown User"

    def add_image_to_chat(self, image_url, max_size=(300, 300)):
        try:
            response = requests.get(image_url, stream=True)
            response.raise_for_status()
            image_data = response.content
            image = Image.open(io.BytesIO(image_data))
            image.thumbnail(max_size, Image.Resampling.LANCZOS)

            # Ensure image is in RGBA mode for PhotoImage compatibility
            image = image.convert('RGBA')

            # Explicitly load the image data to ensure it's fully processed
            image.load()

            photo = ImageTk.PhotoImage(image)
            
            self.chat_history.config(state=tk.NORMAL)
            self.chat_history.image_create(tk.END, image=photo)
            self.chat_history.insert(tk.END, "\n") # Add a newline after the image
            self.chat_history.config(state=tk.DISABLED)
            self.chat_history.see(tk.END)
            
            self.chat_history_image_references.append(photo) # Keep a reference
        except Exception as e:
            self.add_message("System", f"Error loading image from {image_url}: {e}")

    def send_message(self, event):
        message_text = self.chat_input.get()
        if message_text and self.current_group_id:
            try:
                payload = {"text": message_text}
                response = requests.post(f"http://127.0.0.1:3000/groups/{self.current_group_id}/messages", json=payload)
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
            self.chat_history.tag_configure("like_message", foreground="#ff69b4") # Pink for likes
            self.chat_history.insert(tk.END, f"{message}\n", "like_message")
        else:
            # User tag
            user_font = font.Font(self.chat_history, self.chat_history.cget("font"))
            user_font.configure(weight="bold")
            self.chat_history.tag_configure("user_tag", font=user_font, foreground="#87ceeb")
            
            # Timestamp
            if timestamp is None:
                timestamp = datetime.now()
            timestamp_str = timestamp.strftime("%H:%M")
            self.chat_history.tag_configure("timestamp", foreground="#a9a9a9")

            self.chat_history.insert(tk.END, f"[{timestamp_str}] ", "timestamp")
            self.chat_history.insert(tk.END, f"{user}: ", "user_tag")
            self.chat_history.insert(tk.END, f"{message}\n")
        
        self.chat_history.config(state=tk.DISABLED)
        self.chat_history.see(tk.END)

    def process_message_queue(self):
        try:
            while not self.message_queue.empty():
                message_data = self.message_queue.get_nowait()
                # GroupMe push messages have a 'subject' field for the actual message
                subject = message_data.get("subject")
                if subject:
                    message_group_id = subject.get("group_id")
                    if message_group_id == self.current_group_id:
                        user = subject.get('name', 'Unknown')
                        text = subject.get('text', '')
                        created_at = datetime.fromtimestamp(subject.get('created_at', 0))
                        self.add_message(user, text, created_at)
                    # else: # Optionally, handle messages for other groups (e.g., notifications)
                    #     print(f"Received message for unselected group {message_group_id}: {subject.get('text')}")
                else:
                    print(f"Received non-subject message: {message_data}")
        finally:
            self.after(100, self.process_message_queue)

if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("800x600")
    app = HexChatUI(master=root)
    app.mainloop()
