# PatchMind frontend — Vite dev server with hot reload.
FROM node:20-bookworm-slim

ENV CHOKIDAR_USEPOLLING=true \
    CHOKIDAR_INTERVAL=300

WORKDIR /app

# Install deps first for layer caching. In dev, ./frontend is bind-mounted over
# /app but the anonymous volume for /app/node_modules (see docker-compose.yml)
# preserves these installed modules.
COPY package.json ./
COPY package-lock.jso[n] ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
