FROM node:18-alpine
WORKDIR /srv
COPY package.json ./
RUN npm install --omit=dev
COPY shared ./shared
COPY payment-service/index.js ./payment-service/index.js
WORKDIR /srv/payment-service
ENV PORT=3002
EXPOSE 3002
CMD ["node", "index.js"]
