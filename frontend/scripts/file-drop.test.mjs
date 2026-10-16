import assert from 'node:assert/strict'
import { test } from 'node:test'
import { listenForFileDrops } from '../src/fileDrop.ts'

function setup() {
  const target = new EventTarget()
  Object.assign(target, { innerWidth: 1280, innerHeight: 800, document: new EventTarget() })
  const changes = [], uploads = []
  const dispose = listenForFileDrops(target, value => changes.push(value), files => uploads.push(files))
  function dispatch(type, options = {}) {
    const event = new Event(type, { cancelable: true })
    Object.assign(event, { dataTransfer: { types: ['Files'], files: [], dropEffect: 'none' }, clientX: 200, clientY: 200, relatedTarget: null }, options)
    target.dispatchEvent(event)
    return event
  }
  return { target, changes, uploads, dispose, dispatch }
}

test('nested elements do not flicker the overlay; dropping uploads the complete batch once', () => {
  const { dispatch, changes, uploads, dispose } = setup()
  const files = [new File(['pdf'], 'a.pdf'), new File(['text'], 'b.txt')]
  dispatch('dragenter')
  dispatch('dragenter')
  dispatch('dragleave')
  assert.deepEqual(changes, [true])
  const over = dispatch('dragover')
  assert.equal(over.defaultPrevented, true)
  assert.equal(over.dataTransfer.dropEffect, 'copy')
  assert.equal(dispatch('drop', { dataTransfer: { types: ['Files'], files } }).defaultPrevented, true)
  assert.deepEqual(changes, [true, false])
  assert.deepEqual(uploads, [files])
  dispose()
})

test('leaving the window clears the overlay even with unmatched nested entries', () => {
  const { dispatch, changes, dispose } = setup()
  dispatch('dragenter')
  dispatch('dragenter')
  dispatch('dragleave', { clientX: 0 })
  assert.deepEqual(changes, [true, false])
  dispose()
})

test('ordinary text and links keep their native drag behavior', () => {
  const { dispatch, changes, uploads, dispose } = setup()
  for (const type of ['dragenter', 'dragover', 'drop']) {
    assert.equal(dispatch(type, { dataTransfer: { types: ['text/plain'], files: [] } }).defaultPrevented, false)
  }
  assert.deepEqual(changes, [])
  assert.deepEqual(uploads, [])
  dispose()
})

test('dragover recovers a missing dragenter and empty file drops are still prevented', () => {
  const { dispatch, changes, uploads, dispose } = setup()
  dispatch('dragover')
  assert.equal(dispatch('drop').defaultPrevented, true)
  assert.deepEqual(changes, [true, false])
  assert.deepEqual(uploads, [[]])
  dispose()
})

test('cancelled drags, lost focus and a hidden tab reset the overlay', () => {
  const { target, dispatch, changes, dispose } = setup()
  dispatch('dragenter')
  dispatch('dragend')
  dispatch('dragenter')
  dispatch('blur')
  dispatch('dragenter')
  target.document.hidden = true
  target.document.dispatchEvent(new Event('visibilitychange'))
  assert.deepEqual(changes, [true, false, true, false, true, false])
  dispose()
})

test('leaving the submit page removes all upload handlers', () => {
  const { dispatch, changes, uploads, dispose } = setup()
  dispose()
  dispatch('dragenter')
  assert.equal(dispatch('drop').defaultPrevented, false)
  assert.deepEqual(changes, [])
  assert.deepEqual(uploads, [])
})
