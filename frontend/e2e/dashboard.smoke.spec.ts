import { expect, test } from '@playwright/test'

const snapshot = {
  nodes: [],
  stations: [
    { id: 'gs-ashburn', name: 'Ashburn', lat: 39, lon: -77, alt_m: 80, min_elevation_deg: 10 },
    { id: 'gs-madrid', name: 'Madrid', lat: 40, lon: -3, alt_m: 80, min_elevation_deg: 10 },
  ],
  links: [],
  jobs: [],
  plans: [],
  transfers: [],
  settings: { t: 0, playing: false, speed: 10, sim_step_s: 5, scenario_id: 'mvp-thesis' },
}

test('job form, thesis presets, tenant switch, market day', async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const url = route.request().url()
    const method = route.request().method()
    if (url.includes('/snapshot')) return route.fulfill({ json: snapshot })
    if (url.includes('/scenarios')) return route.fulfill({ json: [{ id: 'mvp-thesis', label: 'MVP' }] })
    if (url.includes('/orbital-records')) return route.fulfill({ json: [] })
    if (url.includes('/tenants')) {
      return route.fulfill({
        json: [
          { id: 'local', display_name: 'Local default' },
          { id: 'alpha', display_name: 'Tenant A' },
          { id: 'beta', display_name: 'Tenant B' },
        ],
      })
    }
    if (url.includes('/evaluations/market-day') && method === 'POST') {
      return route.fulfill({
        json: {
          stolen_windows: 0,
          deadline_hit_rate: { alpha: 1, beta: 1 },
          cost_reservation_aware: 1,
          cost_global_cheapest_ignores_tenants: 1,
          seed: 11,
        },
      })
    }
    if (url.includes('/presets/thesis') && method === 'POST') {
      return route.fulfill({
        json: {
          job: { id: 'job-1', state: 'planned', submitted_at: 0, plan_id: 'p1' },
          plan: { id: 'p1', job_id: 'job-1', compute_node_id: 'earth-us-east' },
          sought_t: 100,
        },
      })
    }
    if (url.includes('/jobs') && method === 'POST') {
      return route.fulfill({
        json: {
          job: { id: 'job-2', state: 'planned', submitted_at: 0, plan_id: 'p2' },
          plan: { id: 'p2', job_id: 'job-2', compute_node_id: 'earth-us-east' },
        },
      })
    }
    if (url.includes('/sim/play') || url.includes('/sim/pause')) {
      return route.fulfill({ json: { playing: url.includes('play') } })
    }
    return route.fulfill({ json: {} })
  })

  await page.goto('/')
  await expect(page.getByTestId('job-form')).toBeVisible()
  await page.getByTestId('work').fill('42')
  await page.getByTestId('submit-job').click()

  await page.getByTestId('toggle-examples').click()
  await expect(page.getByTestId('thesis-a')).toBeVisible()
  await page.getByTestId('thesis-b').click()

  await page.getByTestId('toggle-advanced').click()
  await page.getByTestId('tenant-select').selectOption('alpha')
  await page.getByTestId('run-market-day').click()
  await expect(page.getByTestId('market-report')).toBeVisible()
  await expect(page.getByTestId('market-report')).toContainText('Stolen windows')
})
