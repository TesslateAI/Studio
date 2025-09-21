FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install --force --no-optional

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]