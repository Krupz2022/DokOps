
# --- Stage 1: Build ---
FROM node:20-alpine AS build

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

# API requests are proxied by Nginx at /api/ — keep URL relative
ENV VITE_API_URL=/api/v1

RUN npm run build

# --- Stage 2: Serve ---
FROM nginx:stable-alpine

# Copy built assets
COPY --from=build /app/dist /usr/share/nginx/html

# Copy Nginx config (SPA routing + backend proxy + gzip)
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
