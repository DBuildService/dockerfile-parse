"""Instruction boundaries and editing for Dockerfile here-documents."""

import json

import pytest

from tests.fixtures import dfparser

dfparser = dfparser  # pylint: disable=self-assigning-variable


@pytest.mark.parametrize('header', [
    'RUN <<EOF',
    'COPY <<EOF /example.txt',
    'ADD <<EOF /example.txt',
    'ONBUILD RUN <<EOF',
])
@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_heredoc_structure_and_json(dfparser, header, newline):
    body = ['FROM not-a-stage', '# literal comment', '  preserve spaces  ',
            'RUN not-a-continuation \\', '', 'EOF']
    block = newline.join([header] + body) + newline
    original = 'FROM base' + newline + block + 'FROM final' + newline
    dfparser.content = original

    command, value = header.split(' ', 1)
    value += '\n' + '\n'.join(body)
    assert dfparser.structure == [
        {'instruction': 'FROM', 'startline': 0, 'endline': 0,
         'content': 'FROM base' + newline, 'value': 'base'},
        {'instruction': command, 'startline': 1, 'endline': 7,
         'content': block, 'value': value},
        {'instruction': 'FROM', 'startline': 8, 'endline': 8,
         'content': 'FROM final' + newline, 'value': 'final'},
    ]
    assert json.loads(dfparser.json) == [{'FROM': 'base'}, {command: value}, {'FROM': 'final'}]
    assert dfparser.content == original


@pytest.mark.parametrize(('opener', 'terminator'), [
    ('<<EOF', 'EOF'),
    ('<< EOF', 'EOF'),
    ('3<<EOF', 'EOF'),
    ("<<'EOF'", 'EOF'),
    ('<<"EOF"', 'EOF'),
    ('<<EO"F"', 'EOF'),
    (r"<<eo\'f", "eo'f"),
    (r'<<"E\$OF"', 'E$OF'),
    (r'<<"E\\OF"', 'E\\OF'),
    (r'<<"E\`OF"', r'E\`OF'),
    ('<<$EOF', '$EOF'),
    ('<<" "', ' '),
    ("<<''EOF", 'EOF'),
    ('<<-EOF', '\tEOF'),
    ('<< -EOF', '-EOF'),
])
def test_heredoc_delimiters(dfparser, opener, terminator):
    dfparser.content = 'RUN cat {}\nFROM payload\n{}\nFROM next\n'.format(opener, terminator)
    assert dfparser.structure == [
        {'instruction': 'RUN', 'startline': 0, 'endline': 2,
         'content': 'RUN cat {}\nFROM payload\n{}\n'.format(opener, terminator),
         'value': 'cat {}\nFROM payload\n{}'.format(opener, terminator)},
        {'instruction': 'FROM', 'startline': 3, 'endline': 3,
         'content': 'FROM next\n', 'value': 'next'},
    ]


@pytest.mark.parametrize('header', [
    'RUN echo "<<EOF"',
    r'RUN echo \<\<EOF',
    'RUN cat <<<EOF',
    'RUN cat<<EOF',
    'RUN ١<<EOF',
    'RUN cat <<\u00a0EOF',
    'RUN cat << \u00a0EOF',
    'RUN cat <<- EOF',
    "RUN cat <<''",
    'RUN cat <<""',
    'RUN ["echo", "<<EOF"]',
    'COPY ["<<EOF", "/example.txt"]',
    'ENV TEXT=<<EOF',
    'ONBUILD RUN',
])
def test_non_heredoc_tokens_leave_following_instruction(dfparser, header):
    command, value = header.split(' ', 1)
    dfparser.content = header + '\nFROM next\n'
    assert dfparser.structure == [
        {'instruction': command, 'startline': 0, 'endline': 0,
         'content': header + '\n', 'value': value},
        {'instruction': 'FROM', 'startline': 1, 'endline': 1,
         'content': 'FROM next\n', 'value': 'next'},
    ]


@pytest.mark.parametrize('escape', ['\\', '`'])
def test_multiple_heredocs_after_continued_header(dfparser, escape):
    header = 'COPY <<FIRST {}\n    <<-"SECOND" /example/\n'.format(escape)
    body = 'SECOND\nFIRST\n\t# still payload\n\tFROM payload\n\tSECOND\n'
    dfparser.content = '# escape={}\n'.format(escape) + header + body + 'FROM next\n'
    assert dfparser.structure == [
        {'instruction': 'COMMENT', 'startline': 0, 'endline': 0,
         'content': '# escape={}\n'.format(escape), 'value': 'escape={}'.format(escape)},
        {'instruction': 'COPY', 'startline': 1, 'endline': 7,
         'content': header + body,
         'value': '<<FIRST     <<-"SECOND" /example/\n' + body.rstrip('\n')},
        {'instruction': 'FROM', 'startline': 8, 'endline': 8,
         'content': 'FROM next\n', 'value': 'next'},
    ]


def test_heredoc_payload_does_not_change_stage_context(dfparser):
    block = ('RUN <<EOF\nFROM imaginary\nARG SECRET=payload\n'
             'ENV MODE=payload\nLABEL owner=payload\nCMD false\nEOF\n')
    dfparser.content = ('FROM base\nARG NAME=actual\nENV MODE=actual\n'
                        'LABEL owner=actual\nCMD true\n' + block)
    assert dfparser.parent_images == ['base']
    assert dfparser.baseimage == 'base'
    assert dfparser.args == {'NAME': 'actual'}
    assert dfparser.envs == {'MODE': 'actual'}
    assert dfparser.labels == {'owner': 'actual'}
    assert dfparser.cmd == 'true'
    assert dfparser.context_structure[-1].envs == {'MODE': 'actual'}
    dfparser.baseimage = 'replacement'
    assert dfparser.content == ('FROM replacement\nARG NAME=actual\nENV MODE=actual\n'
                                'LABEL owner=actual\nCMD true\n' + block)


@pytest.mark.parametrize('operation', ['after', 'replace', 'delete'])
def test_editing_heredoc_uses_complete_span(dfparser, operation):
    block = 'RUN <<EOF\nFROM payload\nEOF\n'
    dfparser.content = 'FROM base\n' + block + 'FROM next\n'
    _, heredoc, _ = dfparser.structure
    if operation == 'delete':
        dfparser._delete_instructions('RUN')
        expected = 'FROM base\nFROM next\n'
    elif operation == 'replace':
        dfparser.add_lines_at(heredoc, 'RUN true', replace=True)
        expected = 'FROM base\nRUN true\nFROM next\n'
    else:
        dfparser.add_lines_at(heredoc, 'RUN true', after=True)
        expected = 'FROM base\n' + block + 'RUN true\nFROM next\n'
    assert dfparser.content == expected


@pytest.mark.parametrize('body', ['FROM payload\n', 'EOF \n', '\tEOF\n'])
def test_unterminated_heredoc_rejects_before_mutation(dfparser, body):
    original = 'FROM base\nRUN <<EOF\n' + body
    dfparser.content = original
    with pytest.raises(ValueError, match="Unterminated heredoc 'EOF'.*line 2"):
        dfparser.baseimage = 'replacement'
    assert dfparser.content == original


def test_heredoc_terminator_without_final_newline(dfparser):
    dfparser.content = 'RUN <<EOF\npayload\nEOF'
    assert dfparser.structure == [
        {'instruction': 'RUN', 'startline': 0, 'endline': 2,
         'content': 'RUN <<EOF\npayload\nEOF', 'value': '<<EOF\npayload\nEOF'},
    ]


def test_unterminated_delimiter_quote_rejects_before_mutation(dfparser):
    original = "FROM base\nRUN <<'EOF\npayload\nEOF\n"
    dfparser.content = original
    with pytest.raises(ValueError, match='Unterminated quote in heredoc delimiter'):
        dfparser.baseimage = 'replacement'
    assert dfparser.content == original


def test_heredoc_carriage_returns_preserve_physical_lines(dfparser):
    block = 'RUN <<EOF\npayload\rinside\nEOF\r\r\n'
    dfparser.content = block + 'FROM next\n'
    assert dfparser.lines == ['RUN <<EOF\n', 'payload\rinside\n',
                              'EOF\r\r\n', 'FROM next\n']
    assert dfparser.structure == [
        {'instruction': 'RUN', 'startline': 0, 'endline': 2,
         'content': block, 'value': '<<EOF\npayload\rinside\nEOF'},
        {'instruction': 'FROM', 'startline': 3, 'endline': 3,
         'content': 'FROM next\n', 'value': 'next'},
    ]


@pytest.mark.parametrize('header', ['RUN echo\u00a0<<EOF', 'RUN <<\u00a0<<EOF'])
def test_unicode_whitespace_before_heredoc(dfparser, header):
    dfparser.content = header + '\nFROM payload\nEOF\nFROM next\n'
    assert dfparser.parent_images == ['next']
    assert dfparser.structure[0] == {
        'instruction': 'RUN', 'startline': 0, 'endline': 2,
        'content': header + '\nFROM payload\nEOF\n',
        'value': header[4:] + '\nFROM payload\nEOF',
    }
