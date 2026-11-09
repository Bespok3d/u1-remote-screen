import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import vm from 'node:vm'

// Inside a Fluidd or Mainsail camera tile the screen stayed at the panel's 480x320 pixels in the
// middle of a much larger tile (Lucio, 2026-11-09). It must fill the tile, keeping its proportions.

const SCREEN_FIT_JS = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../files/html/screen-fit.js'), 'utf8')

function loadScreenFit() {
  const context = vm.createContext({})
  vm.runInContext(SCREEN_FIT_JS, context)
  return context
}

const PANEL = { width: 480, height: 320 }

test('in a wide camera tile the screen fills the tile height', () => {
  const { screenZoom } = loadScreenFit()
  assert.equal(screenZoom(true, { width: 1146, height: 764 }, PANEL), 764 / 320)
})

test('in a tall camera tile the screen fills the tile width', () => {
  const { screenZoom } = loadScreenFit()
  assert.equal(screenZoom(true, { width: 600, height: 900 }, PANEL), 600 / 480)
})

test('in a tile smaller than the panel the screen shrinks to fit', () => {
  const { screenZoom } = loadScreenFit()
  assert.equal(screenZoom(true, { width: 240, height: 160 }, PANEL), 0.5)
})

test('in its own tab the screen keeps the double size', () => {
  const { screenZoom } = loadScreenFit()
  assert.equal(screenZoom(false, { width: 1146, height: 764 }, PANEL), 2)
})
