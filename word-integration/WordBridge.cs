// Local Microsoft Word adapter. All production writes target an explicitly
// snapshotted active document and only PaperQuick ADDIN fields. Never Save/Quit
// the user's application. selftest creates and owns a separate Word instance.
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

internal static class WordBridge {
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 32000000, RecursionLimit = 100 };
    const string Citation = "PAPERQUICK_CITATION";
    const string Bibliography = "PAPERQUICK_BIBLIO";
    static Dictionary<string, object> D(object value) { return (Dictionary<string, object>)value; }
    static object V(Dictionary<string, object> value, string key, object fallback = null) { object answer; return value.TryGetValue(key, out answer) ? answer : fallback; }
    static string S(object value) { return Convert.ToString(value); }
    static int I(object value) { return Convert.ToInt32(value); }
    static List<object> L(object value) { return value == null ? new List<object>() : ((IEnumerable)value).Cast<object>().ToList(); }
    static Dictionary<string, object> Obj(params object[] pairs) { var result = new Dictionary<string, object>(); for (int i = 0; i < pairs.Length; i += 2) result[S(pairs[i])] = pairs[i + 1]; return result; }
    static void Need(bool pass, string message) { if (!pass) throw new InvalidOperationException(message); }
    static string Hash(string text) { using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(text))).Replace("-", "").ToLowerInvariant(); }
    static string RollbackToken(dynamic document) {
        // WordOpenXML includes volatile package data, so even reads can change
        // it. Use stable state instead. Result formatting is always preceded by
        // changing ADDIN code to QUOTE; a failed rich-text write is detectable
        // from that code change. Include fldLock for a lock-only failure.
        // A failed first COM call must NEVER undo an unrelated earlier edit.
        var state = new StringBuilder(S(document.Content.Text));
        dynamic fields = document.Content.Fields;
        for (int n = 1; n <= (int)fields.Count; ++n) {
            dynamic field = fields[n];
            state.Append("\n").Append((int)field.Code.Start).Append(":").Append(S(field.Code.Text)).Append(":").Append(S(field.Result.Text)).Append(":").Append((bool)field.Locked);
        }
        return Hash(state.ToString());
    }
    static void CheckEditableControls(dynamic document, int start, int end) {
        dynamic controls = document.ContentControls;
        for (int n = 1; n <= (int)controls.Count; ++n) {
            dynamic control = controls[n], range = control.Range;
            if ((int)range.StoryType != 1) continue;
            int left = (int)range.Start, right = (int)range.End;
            bool overlaps = start == end ? start >= left && start <= right : start < right && end > left;
            bool removesControl = start < end && start <= left && end >= right;
            Need(!(overlaps && (bool)control.LockContents) && !(removesControl && (bool)control.LockContentControl),
                 "这个位置或引用所在的内容区域已锁定。请移到可编辑的正文位置，或先在 Word 中解除该区域锁定。");
        }
    }
    static string AsciiRtf(string rtf) {
        var output = new StringBuilder();
        foreach (char c in rtf) {
            if (c <= 127) output.Append(c);
            else output.Append("{\\uc1\\u").Append((short)c).Append("?}");
        }
        return output.ToString();
    }

    [STAThread]
    static int Main(string[] args) {
        if (args.Length != 2) return 2;
        object answer;
        try {
            var request = D(Json.DeserializeObject(File.ReadAllText(args[0], Encoding.UTF8)));
            string action = S(V(request, "action"));
            object result;
            if (action == "health") {
                result = Obj("installed", Type.GetTypeFromProgID("Word.Application") != null, "platform", "Windows desktop Word");
            } else if (action == "selftest") {
                result = SelfTest(request);
            } else {
                dynamic app;
                try { app = Marshal.GetActiveObject("Word.Application"); }
                catch { throw new InvalidOperationException("请先打开 Microsoft Word，并将光标放在需要插入引用的文档正文中。"); }
                Need((int)app.Documents.Count > 0, "请先在 Word 中打开一份文档，再插入引用。");
                if (action == "snapshot") result = Snapshot(app);
                else if (action == "apply") result = Apply(app, D(request["snapshot"]), D(request["operations"]));
                else throw new InvalidOperationException("不支持的 Word 操作。");
            }
            answer = Obj("ok", true, "result", result);
        } catch (Exception ex) {
            string message = ex is InvalidOperationException ? ex.Message : "Word 未完成操作。请关闭 Word 中的对话框，确认文档可编辑后重试。";
            answer = Obj("ok", false, "error", message, "detail", ex.ToString());
        }
        File.WriteAllText(args[1], Json.Serialize(answer), new UTF8Encoding(false));
        return 0;
    }

    static Dictionary<string, object> Parse(dynamic field) {
        string code = ((string)field.Code.Text).Trim();
        var match = Regex.Match(code, @"^ADDIN\s+(PAPERQUICK_CITATION|PAPERQUICK_BIBLIO)\s+(\S+)\s*$", RegexOptions.CultureInvariant);
        if (!match.Success) {
            Need(!Regex.IsMatch(code, @"^ADDIN\s+PAPERQUICK_(CITATION|BIBLIO)\b"), "文档中有一条引用信息不完整，请先撤销最近的引用编辑，或移除这条引用后重新插入。");
            return null;
        }
        Dictionary<string, object> payload;
        try { payload = D(Json.DeserializeObject(Encoding.UTF8.GetString(Convert.FromBase64String(match.Groups[2].Value)))); }
        catch { throw new InvalidOperationException("文档中有一条引用信息无法读取，请在 Word 中撤销最近的修改后重试。"); }
        Need(!String.IsNullOrWhiteSpace(S(V(payload, "id"))), "文档中的引用缺少识别信息，请移除这条引用后重新插入。");
        return Obj("id", S(payload["id"]), "kind", match.Groups[1].Value == Citation ? "citation" : "bibliography", "payload", payload,
                   "start", (int)field.Code.Start - 1, "end", (int)field.Result.End + 1, "text", S(field.Result.Text));
    }

    static Dictionary<string, object> Snapshot(dynamic app) {
        dynamic document = app.ActiveDocument;
        dynamic window = app.ActiveWindow;
        dynamic selection = app.Selection.Range;
        var fields = new List<object>();
        var fingerprint = new StringBuilder(S(document.Content.Text));
        dynamic allFields = document.Content.Fields;
        for (int n = 1; n <= (int)allFields.Count; ++n) {
            dynamic field = allFields[n];
            fingerprint.Append("\n").Append((int)field.Code.Start).Append(":").Append(S(field.Code.Text)).Append(":").Append(S(field.Result.Text));
            var parsed = Parse(field);
            if (parsed != null) fields.Add(parsed);
        }
        return Obj("document", Obj("name", S(document.Name), "full_name", S(document.FullName), "window", (int)window.Hwnd,
                    "read_only", (bool)document.ReadOnly, "protected", (int)document.ProtectionType != -1, "track_revisions", (bool)document.TrackRevisions),
                   "selection", Obj("start", (int)selection.Start, "end", (int)selection.End, "story_type", (int)selection.StoryType),
                   "fields", fields, "fingerprint", Hash(fingerprint.ToString()));
    }

    static void Validate(Dictionary<string, object> expected, Dictionary<string, object> actual) {
        var a = D(actual["document"]); var e = D(expected["document"]);
        Need(S(a["full_name"]) == S(e["full_name"]) && S(a["name"]) == S(e["name"]) && I(a["window"]) == I(e["window"]), "Word 中的文档已切换。请返回需要编辑的文档，再重新读取引用。");
        Need(S(actual["fingerprint"]) == S(expected["fingerprint"]), "Word 文档刚刚发生了变化。请重新读取引用后再操作。");
        var sa = D(actual["selection"]); var se = D(expected["selection"]);
        Need(I(sa["start"]) == I(se["start"]) && I(sa["end"]) == I(se["end"]) && I(sa["story_type"]) == I(se["story_type"]), "Word 中的光标位置已改变。请重新读取插入位置后再操作。");
        Need(I(sa["story_type"]) == 1, "请将光标放在文档正文中。脚注、页眉和文本框暂不支持插入引用。");
        Need(!(bool)a["read_only"] && !(bool)a["protected"], "这份 Word 文档目前只读或受保护，请先启用编辑后再插入引用。");
        Need(!(bool)a["track_revisions"], "请先关闭 Word 的“修订”，再插入或更新引用。已有修订内容会保留。");
    }

    static string Code(string kind, Dictionary<string, object> payload) {
        Need(kind == "citation" || kind == "bibliography", "引用类型不正确，请重新选择操作。");
        Need(!String.IsNullOrWhiteSpace(S(V(payload, "id"))), "引用缺少识别信息，请重新选择文献。");
        return " ADDIN " + (kind == "citation" ? Citation : Bibliography) + " " + Convert.ToBase64String(Encoding.UTF8.GetBytes(Json.Serialize(payload))) + " ";
    }

    sealed class Prepared {
        public Dictionary<string, object> Operation;
        public string Kind;
        public dynamic Field;
        public dynamic RichText;
    }

    static Dictionary<string, object> Apply(dynamic app, Dictionary<string, object> expected, Dictionary<string, object> operations, string testFailure = null) {
        var actual = Snapshot(app); Validate(expected, actual);
        dynamic document = app.ActiveDocument;
        dynamic targetWindow = app.ActiveWindow;
        dynamic originalSelection = app.Selection.Range.Duplicate;
        var existing = new Dictionary<string, object>();
        var priorLocks = new Dictionary<string, bool>();
        dynamic allFields = document.Content.Fields;
        for (int n = 1; n <= (int)allFields.Count; ++n) {
            dynamic field = allFields[n]; var parsed = Parse(field); if (parsed == null) continue;
            string id = S(parsed["id"]);
            Need(!existing.ContainsKey(id), "检测到复制产生的重复引用标记。请删除重复粘贴的引用，再通过“插入引用”添加。");
            existing[id] = (object)field;
            priorLocks[id] = (bool)field.Locked;
        }
        var updates = L(V(operations, "updates"));
        var remove = L(V(operations, "remove"));
        var insert = V(operations, "insert") == null ? null : D(operations["insert"]);
        Need(updates.Count + remove.Count + (insert == null ? 0 : 1) > 0, "没有需要更新的引用。");
        var touched = new HashSet<string>(); var prepared = new List<Prepared>();
        foreach (object item in updates) {
            var op = D(item); string id = S(op["id"]);
            Need(existing.ContainsKey(id) && touched.Add(id), "引用已变化或重复，请重新读取文档后再操作。");
            var payload = D(op["payload"]); Need(S(V(payload,"id")) == id, "引用标记不能在更新时改变。");
            dynamic field = existing[id]; var parsed = Parse(field);
            Need((int)field.Result.Fields.Count == 0, "这条引用内包含其他自动内容，请先在 Word 中检查后再更新。");
            CheckEditableControls(document, I(parsed["start"]), I(parsed["end"]));
            prepared.Add(new Prepared { Operation = op, Kind = S(parsed["kind"]), Field = field });
        }
        foreach (object idValue in remove) {
            string id = S(idValue); Need(existing.ContainsKey(id) && touched.Add(id), "要移除的引用已变化，请重新读取文档。");
            dynamic field = existing[id];
            Need((int)field.Result.Fields.Count == 0, "这条引用内包含其他自动内容，请先在 Word 中检查后再移除。");
            CheckEditableControls(document, (int)field.Code.Start - 1, (int)field.Result.End + 1);
        }
        if (insert != null) {
            var selection = D(actual["selection"]); int start = I(selection["start"]);
            Need(start == I(selection["end"]), "请在 Word 中点击插入位置，取消文字选中，再插入引用。");
            CheckEditableControls(document, start, start);
            for (int n = 1; n <= (int)allFields.Count; ++n) {
                dynamic field = allFields[n];
                Need(start < (int)field.Code.Start - 1 || start >= (int)field.Result.End + 1, "光标位于已有引用或其他自动内容中，请先移到引用外面再插入。");
            }
            string kind = S(insert["kind"]); var payload = D(insert["payload"]); Code(kind, payload);
            Need(!existing.ContainsKey(S(payload["id"])), "这条引用已经插入，请重新选择插入操作。");
            prepared.Add(new Prepared { Operation = insert, Kind = kind });
        }
        string temporary = Path.Combine(Path.GetTempPath(), "PaperQuickWordRich-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temporary);
        var scratch = new List<object>();
        bool recording = false, changed = false, undoableWrite = false; string rollbackToken = null;
        try {
            // Prepare all RTF before starting the target document's undo record.
            // Switching documents while a custom undo record is open breaks it.
            foreach (var p in prepared) {
                string rtf = S(V(p.Operation, "result_rtf"));
                Need(rtf.StartsWith("{\\rtf", StringComparison.Ordinal) && rtf.Length <= 8000000, "引用排版内容不完整，请重新生成引用。");
                Need(!Regex.IsMatch(rtf, @"\\(object|objdata|field|filetbl|pict)\b", RegexOptions.IgnoreCase), "引用排版中含有不支持的内容，请重新生成。");
                Code(p.Kind, D(p.Operation["payload"]));
                string path = Path.Combine(temporary, Guid.NewGuid().ToString("N") + ".rtf");
                File.WriteAllText(path, AsciiRtf(rtf), Encoding.ASCII);
                dynamic temp = app.Documents.Open(FileName: path, ConfirmConversions: false, ReadOnly: true, AddToRecentFiles: false, Visible: false, NoEncodingDialog: true);
                scratch.Add((object)temp);
                dynamic rich = temp.Content.Duplicate;
                if ((int)rich.End > (int)rich.Start && S(rich.Text).EndsWith("\r", StringComparison.Ordinal)) rich.End = (int)rich.End - 1;
                Need((int)rich.End > (int)rich.Start, "引用排版内容为空，请检查文献信息后重试。");
                p.RichText = rich;
            }
            targetWindow.Activate(); originalSelection.Select();
            Validate(expected, Snapshot(app));
            Need(!(bool)app.UndoRecord.IsRecordingCustomRecord, "Word 正在进行另一项编辑，请稍后再插入引用。");
            // Recheck controls immediately before writing: they can be locked
            // while RTF preparation is in progress, without changing body text.
            foreach (var p in prepared) {
                if ((object)p.Field == null) CheckEditableControls(document, (int)originalSelection.Start, (int)originalSelection.End);
                else CheckEditableControls(document, (int)p.Field.Code.Start - 1, (int)p.Field.Result.End + 1);
            }
            foreach (object id in remove) { dynamic field = existing[S(id)]; CheckEditableControls(document, (int)field.Code.Start - 1, (int)field.Result.End + 1); }
            rollbackToken = RollbackToken(document);
            app.UndoRecord.StartCustomRecord("文献直达：更新引用与参考文献"); recording = true;
            dynamic inserted = null;
            // Existing COM field objects track their positions while earlier text grows.
            foreach (var p in prepared) {
                dynamic field = p.Field;
                changed = true;
                if (testFailure == "before-write") throw new InvalidOperationException("Test: simulated failure before first COM write.");
                if (field == null) {
                    dynamic range = originalSelection.Duplicate; range.Collapse(1);
                    field = document.Fields.Add(range, 35, "\" \"", false);
                    undoableWrite = true;
                    inserted = field;
                }
                field.Locked = false;
                if (testFailure == "after-unlock") throw new InvalidOperationException("Test: simulated failure after changing field lock.");
                field.Code.Text = " QUOTE \" \" ";
                undoableWrite = true;
                if (testFailure == "after-code") throw new InvalidOperationException("Test: simulated failure after an undoable field-code write.");
                field.Result.FormattedText = p.RichText.FormattedText;
                field.Code.Text = Code(p.Kind, D(p.Operation["payload"]));
                field.Locked = true;
            }
            foreach (object id in remove) { changed = true; dynamic field = existing[S(id)]; field.Delete(); undoableWrite = true; }
            app.UndoRecord.EndCustomRecord(); recording = false;
            if (inserted != null) document.Range((int)inserted.Result.End + 1, (int)inserted.Result.End + 1).Select();
            return Snapshot(app);
        } catch (Exception error) {
            // Field.Locked itself is not an undoable Word operation. Restore it
            // explicitly before deciding whether this batch has an undo item.
            // Otherwise a lock-only failure could undo the user's earlier edit.
            foreach (var item in existing) {
                try { dynamic field = item.Value; field.Locked = priorLocks[item.Key]; } catch { }
            }
            if (recording) { try { app.UndoRecord.EndCustomRecord(); } catch { } recording = false; }
            if (changed) {
                bool actualChange;
                try { actualChange = rollbackToken != RollbackToken(document); }
                catch { throw new InvalidOperationException("Word 暂时无法确认这次操作的结果。请先检查文档中的引用是否已改变，确认后再操作。文件尚未自动保存。"); }
                if (!actualChange) throw new InvalidOperationException("这次引用更新没有完成，文档内容未改变。" + (error is InvalidOperationException ? error.Message : "请检查 Word 后重试。"));
                if (!undoableWrite) throw new InvalidOperationException("Word 未能确认这次引用编辑是否完成。请先检查文档中的引用，确认后再操作。文件尚未自动保存。");
                bool restored = false;
                try { restored = (bool)document.Undo(1); } catch { }
                if (restored) {
                    dynamic fields = document.Content.Fields;
                    for (int n = 1; n <= (int)fields.Count; ++n) {
                        try { dynamic field = fields[n]; var info = Parse(field); if (info != null && priorLocks.ContainsKey(S(info["id"]))) field.Locked = priorLocks[S(info["id"])]; } catch { }
                    }
                }
                if (!restored) throw new InvalidOperationException("引用更新中断，请在 Word 中按 Ctrl+Z 检查并撤销这次编辑。文件尚未自动保存。");
                throw new InvalidOperationException("这次引用更新没有完成，已撤回本次编辑。" + (error is InvalidOperationException ? error.Message : "请检查 Word 后重试。"));
            }
            throw;
        } finally {
            foreach (dynamic temp in scratch) { try { temp.Close(0); } catch { } }
            try { Directory.Delete(temporary, true); } catch { }
        }
    }

    static string Compact(string text) { return Regex.Replace(text, @"\s+", " ").Trim(); }

    static Dictionary<string, object> SelfTestBatches(dynamic app, dynamic doc, List<object> batches) {
        var checks = new List<string>();
        for (int step = 0; step < batches.Count; ++step) {
            var batch = D(batches[step]);
            string cursor = S(V(batch, "cursor", "end")); int position = (int)doc.Content.End - 1;
            if (cursor == "before") {
                string anchor = S(batch["anchor"]); bool found = false;
                for (int n = 1; n <= (int)doc.Content.Fields.Count; ++n) {
                    dynamic field = doc.Content.Fields[n]; var info = Parse(field);
                    if (info != null && S(info["id"]) == anchor) { position = Math.Max(0, I(info["start"]) - 1); found = true; break; }
                }
                Need(found, "Test: insertion anchor missing.");
            }
            doc.Range(position, position).Select();
            var before = Snapshot(app);
            var after = Apply(app, before, D(batch["operations"]));
            var expected = D(batch["expected_plain"]);
            var fields = L(after["fields"]);
            Need(fields.Count == expected.Count, "Test: CSL field count mismatch at step " + step);
            foreach (object value in fields) {
                var field = D(value); string id = S(field["id"]);
                Need(expected.ContainsKey(id), "Test: unexpected CSL field id.");
                Need(Compact(S(field["text"])) == Compact(S(expected[id])), "Test: rendered CSL text differs at step " + step + ": " + S(field["text"]) + " != " + S(expected[id]));
                var payload = D(field["payload"]);
                Need(S(V(payload, "style_id")) == S(batch["style_id"]), "Test: CSL style metadata lost.");
                if (S(field["kind"]) == "citation") {
                    foreach (object item in L(payload["items"])) Need(D(item).ContainsKey("itemData"), "Test: embedded CSL metadata lost.");
                }
            }
            if (V(batch, "check_italic") != null || Convert.ToBoolean(V(batch, "check_superscript", false)) || Convert.ToBoolean(V(batch, "check_hanging", false))) {
                bool italicFound = V(batch, "check_italic") == null, superscriptFound = !Convert.ToBoolean(V(batch, "check_superscript", false)), hangingFound = !Convert.ToBoolean(V(batch, "check_hanging", false));
                for (int n = 1; n <= (int)doc.Content.Fields.Count; ++n) {
                    dynamic f = doc.Content.Fields[n]; var info = Parse(f); if (info == null) continue;
                    if (S(info["kind"]) == "bibliography") {
                        if (!italicFound) {
                            dynamic probe = f.Result.Duplicate;
                            if ((bool)probe.Find.Execute(S(batch["check_italic"]))) italicFound = (int)probe.Font.Italic == -1;
                        }
                        if ((float)f.Result.Paragraphs[1].Format.FirstLineIndent < 0) hangingFound = true;
                    } else if ((int)f.Result.Font.Superscript == -1) superscriptFound = true;
                }
                Need(italicFound && superscriptFound && hangingFound, "Test: CSL character/paragraph formatting was not preserved at step " + step + " (italic=" + italicFound + ", superscript=" + superscriptFound + ", hanging=" + hangingFound + ").");
            }
            if (Convert.ToBoolean(V(batch, "undo_check", false))) {
                Need((bool)doc.Undo(1), "Test: CSL batch undo failed.");
                Need(S(Snapshot(app)["fingerprint"]) == S(before["fingerprint"]), "Test: CSL batch undo changed prior document.");
            }
            checks.Add(S(V(batch, "label", "CSL step " + step)));
        }
        return Obj("passed", true, "checks", checks, "document_saved", false);
    }

    static Dictionary<string, object> SelfTest(Dictionary<string, object> request) {
        dynamic app = null, doc = null;
        try {
            app = Activator.CreateInstance(Type.GetTypeFromProgID("Word.Application"));
            app.Visible = false; app.DisplayAlerts = 0;
            doc = app.Documents.Add();
            doc.Content.Text = "PaperQuick isolated test.\rReferences:\r";
            if (V(request, "batches") != null) return SelfTestBatches(app, doc, L(request["batches"]));
            doc.Range(23, 23).Select();
            var first = Snapshot(app);
            var payload = Obj("id", Guid.NewGuid().ToString("N"), "style", "test", "items", new object[] { Obj("id", "fixture", "itemData", Obj("title", "Fictional research paper")) });
            var insert = Obj("kind", "citation", "payload", payload, "result_rtf", "{\\rtf1\\ansi [1]}");
            var after = Apply(app, first, Obj("insert", insert));
            Need(L(after["fields"]).Count == 1, "Test: insertion did not create one field.");
            dynamic field = doc.Content.Fields[1];
            Need(S(field.Result.Text) == "[1]", "Test: field result was not retained: " + S(field.Result.Text));
            Need((int)field.Type == 81, "Test: field is not ADDIN.");
            var updated = Apply(app, after, Obj("updates", new object[] { Obj("id", payload["id"], "payload", payload, "result_rtf", "{\\rtf1\\ansi [2]}" ) }));
            Need(S(doc.Content.Fields[1].Result.Text) == "[2]", "Test: update failed.");
            Need((bool)doc.Undo(1), "Test: update undo failed.");
            Need(S(doc.Content.Fields[1].Result.Text) == "[1]", "Test: update was not one undo step.");
            var beforeDelete = Snapshot(app);
            Apply(app, beforeDelete, Obj("remove", new object[] { payload["id"] }));
            Need((int)doc.Content.Fields.Count == 0, "Test: remove failed.");
            Need((bool)doc.Undo(1), "Test: remove undo failed.");
            Need((int)doc.Content.Fields.Count == 1, "Test: remove undo lost field.");
            bool staleRejected = false;
            try { Apply(app, first, Obj("insert", insert)); } catch (InvalidOperationException) { staleRejected = true; }
            Need(staleRejected, "Test: stale snapshot accepted.");
            doc.TrackRevisions = true;
            bool trackedRejected = false;
            try { Apply(app, Snapshot(app), Obj("remove", new object[] { payload["id"] })); } catch (InvalidOperationException) { trackedRejected = true; }
            Need(trackedRejected, "Test: tracked revisions accepted.");
            doc.TrackRevisions = false;
            var beforeInvalid = Snapshot(app);
            bool badRtfRejected = false;
            try { Apply(app, beforeInvalid, Obj("updates", new object[] { Obj("id", payload["id"], "payload", payload, "result_rtf", "{\\rtf1\\object forbidden}") })); }
            catch (InvalidOperationException) { badRtfRejected = true; }
            Need(badRtfRejected && S(Snapshot(app)["fingerprint"]) == S(beforeInvalid["fingerprint"]), "Test: invalid RTF changed document.");
            doc.Protect(Type: 3, NoReset: true, Password: "PaperQuick-test-only");
            bool protectionRejected = false;
            try { Apply(app, Snapshot(app), Obj("remove", new object[] { payload["id"] })); } catch (InvalidOperationException) { protectionRejected = true; }
            doc.Unprotect(Password: "PaperQuick-test-only");
            Need(protectionRejected, "Test: protected document accepted.");
            // Locking one content control does not set Document.ProtectionType.
            // Check both a directly locked control and a locked parent control,
            // after an unrelated edit which must stay on Word's undo stack.
            for (int nested = 0; nested < 2; ++nested) {
                int lockedAt = (int)doc.Content.End - 1;
                dynamic outer = doc.ContentControls.Add(0, doc.Range(lockedAt, lockedAt));
                outer.Range.Text = "Locked control test area";
                dynamic inside = outer;
                if (nested == 1) inside = doc.ContentControls.Add(0, doc.Range((int)outer.Range.Start + 7, (int)outer.Range.Start + 14));
                outer.LockContents = true; outer.LockContentControl = true;
                doc.Content.InsertBefore("Keep prior edit. ");
                int spot = (int)inside.Range.Start + 1; doc.Range(spot, spot).Select();
                string lockedToken = RollbackToken(doc);
                var extraPayload = Obj("id", Guid.NewGuid().ToString("N"), "items", new object[] { Obj("id", "locked-fixture", "itemData", Obj("title", "Locked test")) });
                bool lockedRejected = false; string lockedError = "";
                try { Apply(app, Snapshot(app), Obj("insert", Obj("kind", "citation", "payload", extraPayload, "result_rtf", "{\\rtf1 [9]}"))); }
                catch (InvalidOperationException e) { lockedRejected = e.Message.Contains("锁定"); lockedError = e.Message; }
                Need(lockedRejected && RollbackToken(doc) == lockedToken && S(doc.Content.Text).StartsWith("Keep prior edit. "), "Test: locked control operation altered prior edit: nested=" + nested + ", rejected=" + lockedRejected + ", token=" + (RollbackToken(doc) == lockedToken) + ", previous=" + S(doc.Content.Text).StartsWith("Keep prior edit. ") + ", error=" + lockedError);
                Need((bool)doc.Undo(1) && !S(doc.Content.Text).StartsWith("Keep prior edit. "), "Test: locked rejection consumed prior undo entry.");
                outer.LockContents = false; outer.LockContentControl = false; outer.Delete(true);
            }
            // Simulate a COM call rejected before any write. The empty custom
            // undo record must not cause Undo(1) to remove an earlier user edit.
            doc.Content.InsertBefore("Keep before failure. ");
            int failureAt = (int)doc.Content.End - 1; doc.Range(failureAt, failureAt).Select();
            var failurePayload = Obj("id", Guid.NewGuid().ToString("N"), "items", new object[] { Obj("id", "fail-fixture", "itemData", Obj("title", "Failure test")) });
            string emptyToken = RollbackToken(doc);
            bool emptyRejected = false;
            try { Apply(app, Snapshot(app), Obj("insert", Obj("kind", "citation", "payload", failurePayload, "result_rtf", "{\\rtf1 [9]}")), "before-write"); }
            catch (InvalidOperationException e) { emptyRejected = e.Message.Contains("未改变"); }
            Need(emptyRejected && RollbackToken(doc) == emptyToken && S(doc.Content.Text).StartsWith("Keep before failure. "), "Test: empty batch undid prior user edit.");
            Need((bool)doc.Undo(1) && !S(doc.Content.Text).StartsWith("Keep before failure. "), "Test: empty batch consumed user undo entry.");
            // A lock-only change *is* a mutation and must be reverted, even
            // though the visible text, field code and result are still equal.
            doc.Content.Fields[1].Locked = true;
            doc.Content.InsertBefore("Keep lock-only failure. ");
            failureAt = (int)doc.Content.End - 1; doc.Range(failureAt, failureAt).Select();
            string lockToken = RollbackToken(doc);
            bool lockOnlyRejected = false; string lockError = "";
            try { Apply(app, Snapshot(app), Obj("updates", new object[] { Obj("id", payload["id"], "payload", payload, "result_rtf", "{\\rtf1 [8]}") }), "after-unlock"); }
            catch (InvalidOperationException e) { lockOnlyRejected = e.Message.Contains("未改变"); lockError = e.Message; }
            Need(lockOnlyRejected && RollbackToken(doc) == lockToken && (bool)doc.Content.Fields[1].Locked, "Test: lock-only failure did not restore lock: rejected=" + lockOnlyRejected + ", token=" + (RollbackToken(doc) == lockToken) + ", locked=" + (bool)doc.Content.Fields[1].Locked + ", error=" + lockError);
            Need(S(doc.Content.Text).StartsWith("Keep lock-only failure. "), "Test: lock-only rollback removed prior edit.");
            string codeToken = RollbackToken(doc);
            bool codeFailureReverted = false;
            try { Apply(app, Snapshot(app), Obj("updates", new object[] { Obj("id", payload["id"], "payload", payload, "result_rtf", "{\\rtf1 [8]}") }), "after-code"); }
            catch (InvalidOperationException e) { codeFailureReverted = e.Message.Contains("已撤回"); }
            Need(codeFailureReverted && RollbackToken(doc) == codeToken && S(doc.Content.Text).StartsWith("Keep lock-only failure. "), "Test: partial field update did not roll back safely.");
            // A foreign citation field must remain byte-for-byte unchanged.
            int finish = (int)doc.Content.End - 1;
            dynamic foreign = doc.Fields.Add(doc.Range(finish, finish), 35, "\"Foreign citation\"", false);
            foreign.Code.Text = " ADDIN ZOTERO_ITEM untouched ";
            string foreignCode = S(foreign.Code.Text), foreignText = S(foreign.Result.Text);
            finish = (int)doc.Content.End - 1; doc.Range(finish, finish).Select();
            var bib = Obj("id", Guid.NewGuid().ToString("N"), "style_id", "test");
            var beforeBib = Snapshot(app);
            var withBib = Apply(app, beforeBib, Obj("insert", Obj("kind", "bibliography", "payload", bib, "result_rtf", "{\\rtf1\\ansi Research \\i title\\i0 .\\par 第二篇文献.}"),
                   "updates", new object[] { Obj("id", payload["id"], "payload", payload, "result_rtf", "{\\rtf1\\ansi\\super 3}" ) }));
            Need(L(withBib["fields"]).Count == 2, "Test: bibliography field missing.");
            Need(S(foreign.Code.Text) == foreignCode && S(foreign.Result.Text) == foreignText, "Test: foreign field changed.");
            bool unicode = false, italic = false, superscript = false;
            for (int n = 1; n <= (int)doc.Content.Fields.Count; ++n) {
                dynamic f = doc.Content.Fields[n]; var info = Parse(f); if (info == null) continue;
                if (S(info["kind"]) == "bibliography") {
                    unicode = S(f.Result.Text).Contains("第二篇文献");
                    dynamic probe = f.Result.Duplicate;
                    if ((bool)probe.Find.Execute("title")) italic = (int)probe.Font.Italic != 0;
                } else superscript = (int)f.Result.Font.Superscript != 0;
            }
            Need(unicode && italic && superscript, "Test: RTF formatting/Unicode lost.");
            Need((bool)doc.Undo(1), "Test: grouped bibliography undo failed.");
            var undone = Snapshot(app);
            Need(L(undone["fields"]).Count == 1 && S(doc.Content.Fields[1].Result.Text) == "[1]", "Test: multiple edits not a single undo step.");
            var cursorBefore = Snapshot(app); int cursor = I(D(cursorBefore["selection"])["start"]); doc.Range(0, 0).Select();
            if (cursor != 0) {
                bool movedRejected = false;
                try { Apply(app, cursorBefore, Obj("remove", new object[] { payload["id"] })); } catch (InvalidOperationException) { movedRejected = true; }
                Need(movedRejected, "Test: moved cursor accepted.");
            }
            return Obj("passed", true, "checks", new[] { "insert ADDIN field", "rich result", "update", "single-step undo", "remove and undo", "stale snapshot", "track revisions rejection", "protected document rejection", "invalid RTF no mutation", "locked control preserves prior edit", "locked parent control preserves prior edit", "zero-write failure preserves prior undo", "lock-only mutation rollback", "partial write rollback preserves prior edit", "foreign citation preserved", "bibliography", "Unicode italic superscript", "multi-edit atomic undo", "cursor changed rejection" }, "document_saved", false);
        } finally {
            object ownedDoc = (object)doc, ownedApp = (object)app;
            if (ownedDoc != null) try { doc.Close(0); } catch { }
            if (ownedApp != null) try { app.Quit(0); } catch { }
            if (ownedDoc != null && Marshal.IsComObject(ownedDoc)) Marshal.FinalReleaseComObject(ownedDoc);
            if (ownedApp != null && Marshal.IsComObject(ownedApp)) Marshal.FinalReleaseComObject(ownedApp);
        }
    }
}
