# Stage 1: Build the application
FROM rust:1.82 AS builder

# Set the working directory inside the container
WORKDIR /usr/src/app

# Copy the dependency manifests from the backend directory into the container
COPY ./backend/Cargo.toml ./backend/Cargo.lock ./

# Create a dummy source file and build dependencies to cache them.
# This is a common Docker pattern to speed up builds.
RUN mkdir -p ./src && echo "fn main() {}" > ./src/main.rs
RUN cargo build --release
RUN rm -f ./target/release/deps/backend*

# Copy the actual source code
COPY ./backend/src ./src

# Build the application with the real source code
RUN cargo build --release

# Stage 2: Create the final, small image
FROM debian:bookworm-slim

# Install only the necessary runtime dependencies
RUN apt-get update && apt-get install -y libssl-dev ca-certificates && rm -rf /var/lib/apt/lists/*

# Copy the compiled application from the builder stage
COPY --from=builder /usr/src/app/target/release/backend /usr/local/bin/backend

# Expose the port the backend listens on
EXPOSE 3000

# The command to run when the container starts
CMD ["backend"]
