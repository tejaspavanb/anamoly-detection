import React from 'react'
import * as ReactDOMClient from 'react-dom/client'
import App from './App.jsx'

const rootApi = ReactDOMClient.createRoot ? ReactDOMClient : ReactDOMClient.default

rootApi.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
