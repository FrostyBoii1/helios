# Helios Core — frontend dev image (Vite dev server).
# For production, build static assets (`npm run build`) and serve via a reverse
# proxy / static host. See docs/architecture.md and CHANGES.md.
FROM node:20-alpine

WORKDIR /app

# Install deps first for layer caching. Copy the lockfile and use `npm ci` for
# reproducible, lockfile-exact installs.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
