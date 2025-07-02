use axum::{
    routing::{get, post},
    Router,
    extract::{Path, Json as AxumJson},
    response::Json,
};
use serde::{Deserialize, Serialize};
use std::net::SocketAddr;
use uuid::Uuid;
use dotenv::dotenv;
use std::env;

// This struct matches the top-level API response object for groups from GroupMe.
#[derive(Deserialize, Debug, Serialize)]
struct ApiResponseGroups {
    response: Vec<Group>,
}

// This struct matches the top-level API response object for messages from GroupMe.
#[derive(Deserialize, Debug, Serialize)]
struct ApiResponseMessages {
    response: MessagesResponse,
}

#[derive(Deserialize, Debug, Serialize)]
struct MessagesResponse {
    messages: Vec<Message>,
}

// This struct matches the top-level API response object for a single user from GroupMe.
#[derive(Deserialize, Debug, Serialize)]
struct ApiResponseUser {
    response: User,
}

#[derive(Deserialize, Debug, Serialize, Clone)]
struct Group {
    id: String,
    name: String,
    #[serde(rename = "type")]
    group_type: String,
    description: String,
    image_url: Option<String>,
    creator_user_id: String,
    created_at: i64,
    updated_at: i64,
    members: Vec<Member>,
}

#[derive(Deserialize, Debug, Serialize, Clone)]
struct Member {
    user_id: String,
    nickname: String,
    image_url: Option<String>,
    id: String,
    muted: bool,
    autokicked: bool,
    roles: Vec<String>,
    name: String,
}

#[derive(Deserialize, Debug, Serialize, Clone)]
struct Message {
    id: String,
    group_id: String,
    name: String,
    avatar_url: Option<String>,
    text: Option<String>,
    sender_id: String,
    sender_type: String,
    created_at: i64,
    system: bool,
    attachments: Option<Vec<Attachment>>,
    #[serde(default)]
    favorited_by: Vec<String>,
}

#[derive(Deserialize, Debug, Serialize, Clone)]
struct Attachment {
    #[serde(rename = "type")]
    attachment_type: String,
    url: Option<String>,
}

#[derive(Deserialize, Debug, Serialize)]
struct SendMessagePayload {
    text: String,
}

#[derive(Deserialize, Debug, Serialize, Clone)]
struct User {
    id: String,
    name: String,
    email: String,
    image_url: String,
    phone_number: String,
    created_at: i64,
    updated_at: i64,
    locale: String,
    sms: bool, // Corrected from sms_mode
}

// The main function to fetch groups from the GroupMe API.
async fn get_groups_from_api(token: &str) -> Result<Vec<Group>, Box<dyn std::error::Error>> {
    let mut all_groups = Vec::new();
    let client = reqwest::Client::new();
    let mut page = 1;
    loop {
        let url = format!("https://api.groupme.com/v3/groups?page={}&per_page=100", page);
        let response = client.get(&url)
            .header("X-Access-Token", token)
            .send()
            .await?;

        if !response.status().is_success() {
            let status = response.status();
            let error_text = response.text().await?;
            return Err(format!("API request failed with status {}: {}", status, error_text).into());
        }

        let api_response = response.json::<ApiResponseGroups>().await?;
        if api_response.response.is_empty() {
            break; // No more groups, exit the loop
        }
        all_groups.extend(api_response.response);
        page += 1;
    }
    Ok(all_groups)
}

// Function to fetch messages for a specific group.
async fn get_messages_from_api(group_id: &str, token: &str) -> Result<Vec<Message>, Box<dyn std::error::Error>> {
    let url = format!("https://api.groupme.com/v3/groups/{}/messages?limit=20", group_id);
    let client = reqwest::Client::new();
    let response = client.get(&url)
        .header("X-Access-Token", token)
        .send()
        .await?;

    if !response.status().is_success() {
        let status = response.status();
        let error_text = response.text().await?;
        return Err(format!("API request failed with status {}: {}", status, error_text).into());
    }

    let api_response = response.json::<ApiResponseMessages>().await?;
    Ok(api_response.response.messages)
}

// Function to send a message to a specific group.
async fn send_message_to_api(group_id: &str, token: &str, text: String) -> Result<Message, Box<dyn std::error::Error>> {
    let url = format!("https://api.groupme.com/v3/groups/{}/messages", group_id);
    let client = reqwest::Client::new();
    let unique_id = Uuid::new_v4().to_string();
    let payload = serde_json::json!({
        "message": {
            "source_guid": unique_id,
            "text": text,
        }
    });

    let response = client.post(&url)
        .header("X-Access-Token", token)
        .json(&payload)
        .send()
        .await?;

    if !response.status().is_success() {
        let status = response.status();
        let error_text = response.text().await?;
        return Err(format!("API request failed with status {}: {}", status, error_text).into());
    }

    let sent_message_response = response.json::<serde_json::Value>().await?;
    let message_data = sent_message_response.get("response").and_then(|r| r.get("message")).ok_or("Invalid response format")?;
    let sent_message: Message = serde_json::from_value(message_data.clone())?;

    Ok(sent_message)
}

// Function to get the current user's details.
async fn get_current_user_from_api(token: &str) -> Result<User, Box<dyn std::error::Error>> {
    let url = "https://api.groupme.com/v3/users/me";
    let client = reqwest::Client::new();
    let response = client.get(url)
        .header("X-Access-Token", token)
        .send()
        .await?;

    if !response.status().is_success() {
        let status = response.status();
        let error_text = response.text().await?;
        return Err(format!("API request failed with status {}: {}", status, error_text).into());
    }

    let api_response = response.json::<ApiResponseUser>().await?;
    Ok(api_response.response)
}

// Axum handler to get all groups.
async fn get_all_groups() -> Json<Vec<Group>> {
    let token = env::var("GROUPME_ACCESS_TOKEN").expect("GROUPME_ACCESS_TOKEN must be set");
    match get_groups_from_api(&token).await {
        Ok(groups) => Json(groups),
        Err(e) => {
            eprintln!("Error fetching groups: {}", e);
            Json(vec![] as Vec<Group>)
        }
    }
}

// Axum handler to get messages for a specific group.
async fn get_group_messages(Path(group_id): Path<String>) -> Json<Vec<Message>> {
    let token = env::var("GROUPME_ACCESS_TOKEN").expect("GROUPME_ACCESS_TOKEN must be set");
    match get_messages_from_api(&group_id, &token).await {
        Ok(messages) => Json(messages),
        Err(e) => {
            eprintln!("Error fetching messages for group {}: {}", group_id, e);
            Json(vec![] as Vec<Message>)
        }
    }
}

// Axum handler to send a message to a specific group.
async fn send_group_message(Path(group_id): Path<String>, AxumJson(payload): AxumJson<SendMessagePayload>) -> Json<String> {
    let token = env::var("GROUPME_ACCESS_TOKEN").expect("GROUPME_ACCESS_TOKEN must be set");
    match send_message_to_api(&group_id, &token, payload.text).await {
        Ok(_) => Json("Message sent successfully".to_string()),
        Err(e) => {
            eprintln!("Error sending message to group {}: {}", group_id, e);
            Json(format!("Error sending message: {}", e))
        }
    }
}

// Axum handler to get the current user's details.
async fn get_current_user() -> Json<User> {
    let token = env::var("GROUPME_ACCESS_TOKEN").expect("GROUPME_ACCESS_TOKEN must be set");
    match get_current_user_from_api(&token).await {
        Ok(user) => Json(user),
        Err(e) => {
            eprintln!("Error fetching current user: {}", e);
            // Return a default or empty User struct in case of error
            Json(User {
                id: String::new(),
                name: "Unknown User".to_string(),
                email: String::new(),
                image_url: String::new(),
                phone_number: String::new(),
                created_at: 0,
                updated_at: 0,
                locale: String::new(),
                sms: false, // Corrected from sms_mode
            })
        }
    }
}

#[derive(Serialize)]
struct TokenResponse {
    token: String,
}

async fn get_token() -> Json<TokenResponse> {
    let token = env::var("GROUPME_ACCESS_TOKEN").expect("GROUPME_ACCESS_TOKEN must be set");
    Json(TokenResponse { token })
}

#[tokio::main]
async fn main() {
    dotenv().ok();

    let app = Router::new()
        .route("/groups", get(get_all_groups))
        .route("/groups/:group_id/messages", get(get_group_messages))
        .route("/groups/:group_id/messages", post(send_group_message))
        .route("/user/me", get(get_current_user))
        .route("/token", get(get_token));

    let addr = SocketAddr::from(([0, 0, 0, 0], 3000));
    println!("listening on {}", addr);
    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
