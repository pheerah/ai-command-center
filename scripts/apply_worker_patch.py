with open('center_worker.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_block = """if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError) as exc:
        # Only a classification leaves the worker; provider logs stay local.
        print(f"Adapter error: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(2)"""

new_block = """if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError) as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        print(f"Adapter error: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)"""

content_norm = content.replace('\r\n', '\n')
if old_block in content_norm:
    content_norm = content_norm.replace(old_block, new_block)
    with open('center_worker.py', 'w', encoding='utf-8', newline='\n') as f:
        f.write(content_norm)
    print("SUCCESS: center_worker.py updated")
else:
    print("ERROR: old_block not found in center_worker.py")
