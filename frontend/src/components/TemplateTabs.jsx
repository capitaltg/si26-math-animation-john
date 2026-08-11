import { useState } from 'react'
import { templateLabel } from '../lib/templates'

export default function TemplateTabs({ templates, rejected, activeTemplate, onSwitch }) {
  const [tab, setTab] = useState('picked')
  const picked = templates.find(t => t.template === activeTemplate) ?? null
  const alternatives = templates.filter(t => t.template !== activeTemplate)
  const counts = { picked: picked ? 1 : 0, alternatives: alternatives.length, rejected: rejected.length }
  return (
    <div className="tabs">
      <div role="tablist" aria-label="Template options" className="tabs__list">
        {['picked', 'alternatives', 'rejected'].map(key => (
          <button
            key={key}
            role="tab"
            id={`tab-${key}`}
            aria-selected={tab === key}
            aria-controls={`panel-${key}`}
            tabIndex={tab === key ? 0 : -1}
            className="tabs__tab"
            onClick={() => setTab(key)}
          >
            {key === 'picked' ? 'Picked' : key === 'alternatives' ? 'Alternatives' : 'Rejected'}
            <span className="tabs__count">{counts[key]}</span>
          </button>
        ))}
      </div>
      <div id="panel-picked" role="tabpanel" aria-labelledby="tab-picked" hidden={tab !== 'picked'} className="tabs__panel">
        {picked ? <div className="tabs__row">{templateLabel(picked.template)}</div> : <p className="tabs__empty">No template picked.</p>}
      </div>
      <div id="panel-alternatives" role="tabpanel" aria-labelledby="tab-alternatives" hidden={tab !== 'alternatives'} className="tabs__panel">
        {alternatives.length === 0
          ? <p className="tabs__empty">No alternatives.</p>
          : (
            <ul className="tabs__rows">
              {alternatives.map(t => (
                <li key={t.template}>
                  <button type="button" className="tabs__row tabs__row--action" onClick={() => onSwitch(t.template)}>
                    {templateLabel(t.template)}
                  </button>
                </li>
              ))}
            </ul>
          )}
      </div>
      <div id="panel-rejected" role="tabpanel" aria-labelledby="tab-rejected" hidden={tab !== 'rejected'} className="tabs__panel tabs__panel--scroll">
        {rejected.length === 0
          ? <p className="tabs__empty">Nothing rejected.</p>
          : (
            <ul className="tabs__rows">
              {rejected.map(r => (
                <li key={r.template} className="tabs__row tabs__row--rejected">
                  <span>{templateLabel(r.template)}</span>
                  <span className="tabs__reason">{r.reason}</span>
                </li>
              ))}
            </ul>
          )}
      </div>
    </div>
  )
}
