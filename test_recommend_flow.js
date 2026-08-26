const assert = require('node:assert');
const fs = require('node:fs');
const vm = require('node:vm');

const elements = {};
const element = id => elements[id] ||= {
    hidden: false,
    classList: {
        values: new Set(),
        toggle(name, active) { active ? this.values.add(name) : this.values.delete(name); },
        remove(name) { this.values.delete(name); }
    },
    addEventListener(type, handler) { this[type] = handler; },
    setAttribute() {}, focus() {}, scrollIntoView() {}
};
const searches = [];
const context = vm.createContext({
    document: { getElementById: element },
    searchAndDisplayPlaces: keyword => searches.push(keyword),
    alert() {}, userPosition: {}
});

vm.runInContext(fs.readFileSync('static/js/state.js', 'utf8'), context);
vm.runInContext(fs.readFileSync('static/js/recommend.js', 'utf8'), context);

vm.runInContext("selectFood('치킨')", context);
assert.equal(vm.runInContext('selectedFood', context), '치킨');
assert.equal(element('ai-recommend').hidden, false);
element('ai-no-btn').click();
assert.deepEqual(searches, ['치킨']);

vm.runInContext("selectFood('한식')", context);
element('ai-yes-btn').click();
assert.equal(element('ai-preference-section').hidden, false);
assert.deepEqual(searches, ['치킨']);
