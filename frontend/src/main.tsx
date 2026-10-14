import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter } from "react-router";
import "./styles/index.css";
import { App, createQueryClient } from "./app";
import { routes } from "./routes";

const router = createBrowserRouter(routes);
const client = createQueryClient();

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <App client={client} router={router} />
  </StrictMode>,
);
