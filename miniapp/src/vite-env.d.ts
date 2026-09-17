/// <reference types="vite/client" />

interface Window {
  WebApp?: {
    initData?: string;
    platform?: string;
    version?: string;
  };
}
