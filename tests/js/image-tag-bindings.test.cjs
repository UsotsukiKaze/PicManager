const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
async function edit(groups,mappings,tag='发色'){
    const source=fs.readFileSync(path.join(__dirname,'../../static/js/ui.js'),'utf8');
    const method=source.slice(source.indexOf('    async editImage('),source.indexOf('    async updateImage('));
    let evidence;
    const layer={};
    const context={api:{getImage:async()=>({pixiv_tags:[{name:tag}],groups:groups.map(id=>({id})),characters:[],feature_tags:[{id:1}]}),getGroups:async()=>[],getCharacters:async()=>[],getFeatureTags:async()=>[],request:async()=>mappings},
        auth:{loadFeature:async()=>({cartTagEditor:(_layer,item)=>{evidence=item.match.evidence;return {destroy(){}};}}),loadStyle:async()=>{}},document:{querySelector:()=>layer},
        evidence:null};
    vm.runInNewContext(`class Editor {${method}showModal(){} getThumbnailUrl(){return '/thumb';} escapeHomeRankingText(value){return String(value);} showToast(message){throw Error(message);}}; editor=new Editor();`,context);
    await context.editor.editImage('0011223344');
    return JSON.parse(JSON.stringify(evidence));
}
test('legacy edit shows the matching group-scoped association rather than another group mapping',async()=>{
    assert.deepEqual(await edit([1],[{tag:'发色',target_type:'feature',target_id:2,group_context:2},{tag:'发色',target_type:'feature',target_id:1,group_context:1}]),[{pixiv_tag:'发色',type:'feature',id:1}]);
});
test('ignore mappings and conflicting scopes are never displayed as false bindings',async()=>{
    assert.deepEqual(await edit([1],[{tag:'发色',target_type:'feature',target_id:1,group_context:0},{tag:'发色',target_type:'ignore',target_id:null,group_context:1}]),[]);
    assert.deepEqual(await edit([1,2],[{tag:'发色',target_type:'feature',target_id:1,group_context:1},{tag:'发色',target_type:'feature',target_id:2,group_context:2}]),[]);
});
test('legacy binding normalizes repeated spaces and fullwidth tag names',async()=>{
    assert.deepEqual(await edit([1],[{tag:'A B',target_type:'feature',target_id:1,group_context:0}],'Ａ  Ｂ'),[{pixiv_tag:'Ａ  Ｂ',type:'feature',id:1}]);
});
