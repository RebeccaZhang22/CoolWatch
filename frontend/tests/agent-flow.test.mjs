import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createAgentFlow, advanceAgentFlow, finishAgentFlow } from '../src/agent-flow.js';

const event = (phase, extra = {}) => ({ phase, status: 'running', ...extra });
test('model and environment alternate over multiple rounds without counting heartbeats', () => {
  const flow = createAgentFlow();
  advanceAgentFlow(flow, event('generation'));
  advanceAgentFlow(flow, event('generation', { heartbeat: true }));
  assert.equal(flow.rounds, 1);
  assert.equal(flow.model, 'running');
  advanceAgentFlow(flow, event('generation', { duration_ms: 100 }));
  advanceAgentFlow(flow, event('tool', { detail: 'search_knowledge' }));
  assert.equal(flow.model, 'complete');
  assert.equal(flow.env, 'running');
  advanceAgentFlow(flow, event('retrieval', { status: 'success' }));
  advanceAgentFlow(flow, event('input_guard'));
  assert.equal(flow.active, null);
  advanceAgentFlow(flow, event('generation'));
  assert.equal(flow.rounds, 2);
  assert.equal(flow.model, 'running');
  assert.equal(flow.env, 'complete');
  finishAgentFlow(flow);
  assert.equal(flow.active, null);
  assert.equal(flow.model, 'complete');
});

test('early blocked result does not light unused model or environment', () => {
  const flow = createAgentFlow();
  advanceAgentFlow(flow, event('input_guard'));
  advanceAgentFlow(flow, event('final_response', { message: '正在交付最终答复' }));
  finishAgentFlow(flow);
  assert.deepEqual(flow, createAgentFlow());
});

test('direct answer skips env and delivery does not add a model round', () => {
  const flow = createAgentFlow();
  advanceAgentFlow(flow, event('generation'));
  advanceAgentFlow(flow, event('generation', { duration_ms: 12 }));
  advanceAgentFlow(flow, event('final_response', { message: '正在交付最终答复' }));
  finishAgentFlow(flow);
  assert.equal(flow.rounds, 1);
  assert.equal(flow.env, 'idle');
});

test('execution failure stops the active light and leaves unvisited nodes idle', () => {
  const flow = createAgentFlow();
  advanceAgentFlow(flow, event('generation'));
  finishAgentFlow(flow, true);
  assert.equal(flow.model, 'error');
  assert.equal(flow.env, 'idle');
  assert.equal(flow.active, null);
});

test('tool error remains visible when the model recovers and generates a response', () => {
  const flow = createAgentFlow();
  advanceAgentFlow(flow, event('tool'));
  advanceAgentFlow(flow, event('tool', { status: 'error' }));
  advanceAgentFlow(flow, event('final_response'));
  finishAgentFlow(flow);
  assert.equal(flow.env, 'error');
  assert.equal(flow.model, 'complete');
});

test('each model turn keeps its own check result and a blocked next turn never starts', () => {
  const flow = createAgentFlow();
  const check = (round, status) => event('input_guard', {
    status: status === 'running' ? 'running' : 'success', checkpoint: { round, status },
  });
  advanceAgentFlow(flow, check(1, 'running'));
  advanceAgentFlow(flow, { ...check(1, 'running'), heartbeat: true });
  advanceAgentFlow(flow, check(1, 'safe'));
  advanceAgentFlow(flow, event('generation'));
  advanceAgentFlow(flow, event('tool'));
  advanceAgentFlow(flow, check(2, 'running'));
  assert.equal(flow.active, null);
  advanceAgentFlow(flow, check(2, 'blocked'));
  finishAgentFlow(flow);
  assert.deepEqual(flow.checkpoints, [{ round: 1, status: 'safe' }, { round: 2, status: 'blocked' }]);
  assert.equal(flow.rounds, 1);
  assert.equal(flow.model, 'complete');
  assert.equal(createAgentFlow().checkpoints.length, 0);
});

test('interrupted detection shows an error instead of passing or continuing to spin', () => {
  const flow = createAgentFlow();
  advanceAgentFlow(flow, event('input_guard', { checkpoint: { round: 1, status: 'running' } }));
  finishAgentFlow(flow, true);
  assert.equal(flow.checkpoints[0].status, 'error');
  assert.equal(flow.model, 'idle');
});
