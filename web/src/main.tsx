import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/inter'
import './estilos/base.css'
import './estilos/marco.css'
import './estilos/secciones.css'
import App from './App.tsx'
import { aplicarTema } from './ui/ganchos'

// Antes de pintar nada, para que quien eligió el tema oscuro no vea un
// fogonazo blanco al abrir.
aplicarTema()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
