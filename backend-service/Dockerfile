FROM node:18-alpine
WORKDIR /srv
COPY package.json ./
RUN npm install --omit=dev
COPY shared ./shared
COPY backend-service/index.js ./backend-service/index.js
WORKDIR /srv/backend-service
ENV PORT=3001
EXPOSE 3001
CMD ["node", "index.js"]
