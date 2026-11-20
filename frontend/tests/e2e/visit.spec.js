import {test,expect} from '@playwright/test';
test('guard verifies, explicitly saves, reloads history and confirms exit',async({page})=>{
 const username=process.env.E2E_USERNAME,password=process.env.E2E_PASSWORD;test.skip(!username||!password,'Use dedicated test credentials');
 await page.goto('/');await page.getByLabel('Username').fill(username);await page.getByLabel('Password').fill(password);await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Security overview'})).toBeVisible();
 if(process.env.E2E_SCREENSHOT_PATH)await page.screenshot({path:process.env.E2E_SCREENSHOT_PATH,fullPage:true});
 await page.getByRole('link',{name:'Delivery verification',exact:true}).click();await page.getByRole('button',{name:'+ Manual candidate'}).click();
 await page.getByLabel('Reason / observation').fill('Automated test fixture: guard observation');await page.getByRole('button',{name:'Create candidate',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Review visitor'})).toBeVisible();await page.getByRole('checkbox').check();await page.getByLabel('Destination Flat Number').fill('TEST-101');await page.getByLabel('Destination Resident Name').fill('Automated Test Resident');
 await page.getByRole('button',{name:'Confirm Delivery',exact:true}).click();await expect(page.getByText('Delivery verified. Click Save Event to record the visit.')).toBeVisible();await page.getByRole('button',{name:'Save Event',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Visit history'})).toBeVisible();await expect(page.getByText('TEST-101 · Automated Test Resident')).toBeVisible();await page.reload();await expect(page.getByText('TEST-101 · Automated Test Resident')).toBeVisible();
 await page.getByRole('button',{name:'Confirm exit',exact:true}).first().click();await page.getByLabel('Confirmation reason').fill('Automated test: guard verified departure');await page.getByRole('checkbox').check();await page.getByRole('button',{name:'Complete Visit',exact:true}).click();await expect(page.getByText('COMPLETED',{exact:true}).first()).toBeVisible();await page.getByRole('button',{name:'Sign out'}).click();await expect(page.getByRole('heading',{name:'Sign in to your workspace'})).toBeVisible();
});
