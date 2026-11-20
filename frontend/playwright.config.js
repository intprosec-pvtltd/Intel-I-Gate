import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./tests/e2e',workers:1,reporter:'list',use:{baseURL:process.env.E2E_BASE_URL||'http://localhost:5173',viewport:{width:1440,height:1000},launchOptions:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,args:['--no-sandbox','--disable-dev-shm-usage']}: {}}});
