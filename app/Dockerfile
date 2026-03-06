FROM node:20-alpine

WORKDIR /app

# Install dependencies first (will be preserved in anonymous volume)
COPY package*.json ./
RUN npm install --force && npm cache clean --force

# Copy application code
COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
