import {test,expect} from '@playwright/test';
for(const height of [600,768,1080])test(`sidebar keeps account visible at ${height}px and scrolls only its menu`,async({page})=>{
 await page.setViewportSize({width:1366,height});
 await page.route('**/api/**',route=>{
  const path=new URL(route.request().url()).pathname;
  const data=path==='/api/auth/me'?{id:'admin',role:'admin',email:'admin@example.test'}:path==='/api/system/status'?{timezone:'Asia/Kolkata'}:path==='/api/dashboard/summary'?{cameras:0,connected:0,pending:0,active_visits:0,completed:0}:[];
  return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
 });
 await page.goto('/');await expect(page.getByRole('button',{name:'Sign out'})).toBeVisible();
 const menu=page.locator('.sidebar>nav'),sidebar=page.locator('.app-shell>.sidebar'),footer=page.locator('.sidebar-bottom');
 const initial=await footer.boundingBox();expect(initial.y).toBeGreaterThan(68);expect(initial.y+initial.height).toBeLessThanOrEqual(height);
 expect(await sidebar.evaluate(e=>getComputedStyle(e).overflowY)).toBe('hidden');
 const dimensions=await menu.evaluate(e=>({content:e.scrollHeight,visible:e.clientHeight}));
 if(height<=768){expect(dimensions.content).toBeGreaterThan(dimensions.visible);await menu.evaluate(e=>{e.scrollTop=e.scrollHeight;});await expect(page.locator('.sidebar nav a').last()).toBeInViewport();}
 const before=await page.evaluate(()=>scrollY);await menu.hover();await page.mouse.wheel(0,1500);await page.waitForTimeout(150);
 expect(await page.evaluate(()=>scrollY)).toBe(before);
 const after=await footer.boundingBox();expect(after.y).toBeCloseTo(initial.y,1);expect(after.y+after.height).toBeLessThanOrEqual(height);
 await expect(page.getByRole('button',{name:'Sign out'})).toBeInViewport();
});
