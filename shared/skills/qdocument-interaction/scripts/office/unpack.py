"""Unpack an OOXML file (.docx, .pptx, .xlsx) to a directory with pretty-printed XML.

Merges adjacent text runs only when their rPr (run properties) are identical.
Detects encrypted containers and exits with an error.

Usage:
    python unpack.py <input_file> <output_dir>

Exit codes: 0 = success, 1 = failure, 3 = encrypted file detected
"""
import os
import sys
import xml.dom.minidom
import zipfile


def _is_encrypted(zip_path):
    """Detect encrypted OOXML (EncryptionInfo stream in OLE container or missing [Content_Types].xml)."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            if "[Content_Types].xml" not in names:
                return True
            # Check for Standard XML Encryption marker
            if "EncryptedPackage" in names or "EncryptionInfo" in names:
                return True
        return False
    except zipfile.BadZipFile:
        # Not a valid ZIP — likely OLE compound document (encrypted)
        return True


def _pretty_print_xml(content_bytes):
    """Pretty-print XML content. Returns string."""
    try:
        dom = xml.dom.minidom.parseString(content_bytes)
        pretty = dom.toprettyxml(indent="  ", encoding="UTF-8")
        return pretty.decode("utf-8")
    except Exception:
        return content_bytes.decode("utf-8", errors="replace")


def _merge_runs(xml_text):
    """Merge adjacent w:r elements with identical w:rPr. Simple regex-free approach via DOM."""
    # Only process word/document XML that contains w:r elements
    if "<w:r" not in xml_text:
        return xml_text
    try:
        dom = xml.dom.minidom.parseString(xml_text.encode("utf-8"))
    except Exception:
        return xml_text

    def _get_rpr_text(run_elem):
        for child in run_elem.childNodes:
            if child.nodeType == child.ELEMENT_NODE and child.localName == "rPr":
                return child.toxml()
        return ""

    def _get_run_text(run_elem):
        texts = []
        for child in run_elem.childNodes:
            if child.nodeType == child.ELEMENT_NODE and child.localName == "t":
                texts.append(child.firstChild.nodeValue if child.firstChild else "")
        return "".join(texts)

    # Walk paragraphs and merge adjacent runs with identical rPr
    for para in dom.getElementsByTagNameNS("http://schemas.openxmlformats.org/wordprocessingml/2006/main", "p"):
        runs = [c for c in para.childNodes if c.nodeType == c.ELEMENT_NODE and c.localName == "r"]
        i = 0
        while i < len(runs) - 1:
            curr_rpr = _get_rpr_text(runs[i])
            next_rpr = _get_rpr_text(runs[i + 1])
            if curr_rpr == next_rpr:
                # Merge text from next into current
                curr_text = _get_run_text(runs[i])
                next_text = _get_run_text(runs[i + 1])
                # Find or create t element in current run
                t_elem = None
                for child in runs[i].childNodes:
                    if child.nodeType == child.ELEMENT_NODE and child.localName == "t":
                        t_elem = child
                        break
                if t_elem and t_elem.firstChild:
                    t_elem.firstChild.nodeValue = curr_text + next_text
                    if t_elem.firstChild.nodeValue.startswith(" ") or t_elem.firstChild.nodeValue.endswith(" "):
                        t_elem.setAttribute("xml:space", "preserve")
                # Remove the merged run
                para.removeChild(runs[i + 1])
                runs.pop(i + 1)
            else:
                i += 1

    return dom.toxml(encoding="UTF-8").decode("utf-8")


def unpack(input_file, output_dir):
    """Unpack OOXML file to output directory."""
    if _is_encrypted(input_file):
        print("Error: file is encrypted or password-protected. Decrypt with msoffcrypto-tool first.", file=sys.stderr)
        sys.exit(3)

    os.makedirs(output_dir, exist_ok=True)

    with zipfile.ZipFile(input_file, "r") as zf:
        for name in zf.namelist():
            content = zf.read(name)
            out_path = os.path.join(output_dir, name.replace("/", os.sep))
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            if name.endswith(".xml") or name.endswith(".rels"):
                pretty = _pretty_print_xml(content)
                # Merge runs for word document content
                if "word/" in name and name.endswith(".xml"):
                    pretty = _merge_runs(pretty)
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(pretty)
            else:
                with open(out_path, "wb") as f:
                    f.write(content)


def main():
    if len(sys.argv) != 3:
        print("Usage: unpack.py <input_file> <output_dir>", file=sys.stderr)
        sys.exit(1)

    input_file = sys.argv[1]
    output_dir = sys.argv[2]

    if not os.path.isfile(input_file):
        print("Error: input file not found: " + input_file, file=sys.stderr)
        sys.exit(1)

    unpack(input_file, output_dir)


if __name__ == "__main__":
    main()
