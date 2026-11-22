export const attestViewTemplate = `
<section class="panel">
  <h2>履约核验</h2>
  <div class="fate-banner" v-if="attestFate">
    <strong>核验禁改口命运说明 · {{ attestFate.path }}路径</strong>
    <span class="badge fail" v-if="attestFate.locked">当日锁死</span>
    <span class="badge frozen" v-else>未锁</span>
    <p>{{ attestFate.statement }}</p>
    <p class="hint">禁用：{{ attestFate.forbidden }}。只允许一次正式结论；二次核验正式零增并拒收，偏航记审计。</p>
  </div>
  <p class="hint">对已冻结笼给出唯一的正式结论。同笼同代一经定论即禁改口，不能追加只读意见，也不能换口径。</p>
  <div class="grid-2">
    <div>
      <div class="form-row">
        <div>
          <label>可核验笼（本代尚无正式结论）</label>
          <select v-model.number="attestForm.cage_id">
            <option :value="0">请选择</option>
            <option v-for="c in attestableCages" :key="c.id" :value="c.id">
              {{ c.cage_code }} · {{ fmt(c.available) }} · 代{{ c.generation }}
            </option>
          </select>
          <p class="hint" v-if="!attestableCages.length">当前没有可核验笼：本代均已定论，改口一律拒收。</p>
        </div>
        <div>
          <label>结论（正式）</label>
          <select v-model="attestForm.outcome">
            <option>通过</option>
            <option>违约</option>
          </select>
        </div>
        <div style="grid-column:1/-1">
          <label>证据摘要</label>
          <textarea v-model="attestForm.evidence" placeholder="验收单号 / 违约说明"></textarea>
        </div>
      </div>
      <div class="actions">
        <button class="ok" @click="doAttest" :disabled="!attestForm.cage_id">提交正式核验</button>
      </div>
    </div>
    <div>
      <table>
        <thead>
          <tr><th>时间</th><th>笼</th><th>结论</th><th>笼代</th><th>核验员</th><th>证据</th></tr>
        </thead>
        <tbody>
          <tr v-for="a in attestations" :key="a.id">
            <td>{{ a.created_at }}</td>
            <td>{{ a.cage_code }}</td>
            <td><span class="badge" :class="a.outcome==='通过'?'pass':'fail'">{{ a.outcome }}</span></td>
            <td>{{ a.attest_gen }}</td>
            <td>{{ a.officer }}</td>
            <td>{{ a.evidence }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</section>
`;
