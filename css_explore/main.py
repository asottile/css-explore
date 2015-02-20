from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import argparse
import collections
import io
import os.path
import subprocess
import sys

import pkg_resources
import simplejson


NENV_PATH = '.nenv-css-explore'


class CalledProcessError(ValueError):
    def __init__(self, returncode, out, err):
        super(CalledProcessError, self).__init__(
            'Unexpected returncode ({0})\n'
            'stdout:\n{1}\n'
            'stderr:\n{2}\n'.format(returncode, out, err),
        )


def indent(text):
    lines = text.splitlines()
    return '\n'.join('    ' + line for line in lines) + '\n'


class Charset(collections.namedtuple('Charset', ('charset',))):
    __slots__ = ()

    def to_text(self, **kwargs):
        ignore_charset = kwargs['ignore_charset']
        if ignore_charset:
            return ''
        else:
            return '@charset {0};\n'.format(self.charset)


class KeyFrame(collections.namedtuple('KeyFrame', ('values', 'properties'))):
    __slots__ = ()

    def to_text(self, **kwargs):
        return '{0} {{\n{1}}}\n'.format(
            self.values,
            ''.join(
                property.to_text(**kwargs) for property in self.properties
            ),
        )


class KeyFrames(
        collections.namedtuple('KeyFrames', ('vendor', 'name', 'keyframes'))
):
    __slots__ = ()

    def to_text(self, **kwargs):
        return '@{0}keyframes {1} {{\n{2}}}\n'.format(
            self.vendor,
            self.name,
            indent(''.join(
                keyframe.to_text(**kwargs) for keyframe in self.keyframes
            )),
        )


class MediaQuery(collections.namedtuple('MediaQuery', ('media', 'rules'))):
    __slots__ = ()

    def to_text(self, **kwargs):
        return '@media {0} {{\n{1}}}\n'.format(
            self.media,
            indent(''.join(rule.to_text(**kwargs) for rule in self.rules)),
        )


class Rule(collections.namedtuple('Rule', ('selectors', 'properties'))):
    __slots__ = ()

    def to_text(self, **kwargs):
        ignore_empty_rules = kwargs['ignore_empty_rules']
        if ignore_empty_rules and not self.properties:
            return ''
        return '{0} {{\n{1}}}\n'.format(
            self.selectors,
            ''.join(
                property.to_text(**kwargs) for property in self.properties
            ),
        )


class Property(collections.namedtuple('Property', ('name', 'value'))):
    __slots__ = ()

    def to_text(self, **_):
        return '    {0}: {1};\n'.format(self.name, self.value)


def require_nodeenv():
    # Make it in the current directory, whatevs.
    if os.path.exists(os.path.join(NENV_PATH, 'installed')):
        return

    subprocess.check_call(
        (sys.executable, '-m', 'nodeenv', NENV_PATH, '--prebuilt'),
        stdout=open(os.devnull, 'w'),
        stderr=open(os.devnull, 'w'),
    )
    subprocess.check_call(
        ('{0}/bin/npm'.format(NENV_PATH), 'install', '-g', 'css'),
        stdout=open(os.devnull, 'w'),
        stderr=open(os.devnull, 'w'),
    )

    # Atomically indicate we've installed
    io.open('{0}/installed'.format(NENV_PATH), 'w').close()


def _check_keys(d, keys):
    # All things have these keys
    keys = keys + ('position', 'type')
    assert set(d) <= set(keys), (set(d), set(keys))


def to_property(declaration_dict):
    assert declaration_dict['type'] == 'declaration', declaration_dict['type']
    _check_keys(declaration_dict, ('property', 'value'))
    return Property(declaration_dict['property'], declaration_dict['value'])


def to_charset(charset_dict):
    _check_keys(charset_dict, ('charset',))
    return Charset(charset_dict['charset'])


def to_keyframe(keyframe_dict):
    _check_keys(keyframe_dict, ('declarations', 'values'))
    properties = tuple(
        to_property(declaration_dict)
        for declaration_dict in keyframe_dict['declarations']
    )
    return KeyFrame(
        ', '.join(keyframe_dict['values']),
        properties,
    )


def to_keyframes(keyframes_dict):
    _check_keys(keyframes_dict, ('vendor', 'name', 'keyframes'))
    keyframes = tuple(
        to_keyframe(keyframe_dict)
        for keyframe_dict in keyframes_dict['keyframes']
    )
    return KeyFrames(
        keyframes_dict.get('vendor', ''),
        keyframes_dict['name'],
        keyframes,
    )


def to_media_query(media_query_dict):
    _check_keys(media_query_dict, ('media', 'rules'))
    rules = tuple(
        generic_to_node(node_dict) for node_dict in media_query_dict['rules']
    )
    return MediaQuery(media_query_dict['media'], rules)


def to_rule(rule_dict):
    _check_keys(rule_dict, ('selectors', 'declarations'))
    selectors = ', '.join(rule_dict['selectors'])
    properties = tuple(
        to_property(declaration_dict)
        for declaration_dict in rule_dict['declarations']
    )
    return Rule(selectors, properties)


TO_NODE_TYPES = {
    'charset': to_charset,
    'keyframes': to_keyframes,
    'media': to_media_query,
    'rule': to_rule,
}


def generic_to_node(node_dict):
    return TO_NODE_TYPES[node_dict['type']](node_dict)


def format_css(contents, **kwargs):
    ignore_charset = kwargs.pop('ignore_charset', False)
    ignore_empty_rules = kwargs.pop('ignore_empty_rules', False)
    assert not kwargs, kwargs
    require_nodeenv()

    proc = subprocess.Popen(
        (
            'sh', '-c',
            ". {0}/bin/activate && node '{1}'".format(
                NENV_PATH,
                pkg_resources.resource_filename(  # pylint:disable=no-member
                    'css_explore', 'resources/css_to_json.js',
                ),
            )
        ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out, err = proc.communicate(contents.encode('UTF-8'))
    out, err = out.decode('UTF-8'), err.decode('UTF-8')
    if proc.returncode:
        raise CalledProcessError(proc.returncode, out, err)

    sheet = simplejson.loads(out)['stylesheet']
    rules = tuple(generic_to_node(rule_dict) for rule_dict in sheet['rules'])
    return ''.join(
        rule.to_text(
            ignore_charset=ignore_charset,
            ignore_empty_rules=ignore_empty_rules,
        )
        for rule in rules
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('filename')
    args = parser.parse_args(argv)
    contents = io.open(args.filename).read()
    print(format_css(contents).rstrip())


if __name__ == '__main__':
    exit(main())
