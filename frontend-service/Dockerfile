FROM node:18-alpine
WORKDIR /srv
COPY package.json ./
RUN npm install --omit=dev
COPY shared ./shared
COPY frontend-service/index.js ./frontend-service/index.js
WORKDIR /srv/frontend-service
ENV PORT=3000
EXPOSE 3000
CMD ["node", "index.js"]
