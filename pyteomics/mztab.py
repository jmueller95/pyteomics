import re

import pandas as pd

from collections import OrderedDict

from pyteomics.auxiliary import _file_obj
from pyteomics.auxiliary import cvstr


class _MzTabParserBase(object):
    def _parse_param(self, tuplet):
        """Parse a controlled vocabulary or user specified parameter tuplet
        into a Python object

        Parameters
        ----------
        tuplet : str
            A square brace enclosed tuplet of values describing the parameter

        Returns
        -------
        tuple
            The reduced representation of the parameter
        """
        cv, acc, name, value = re.split(r"\s*,\s*", tuplet[1:-1])
        param_name = cvstr(name, acc)
        if value:
            return (param_name, value)
        else:
            return (param_name)

    def _cast_value(self, value):
        """Convert a cell value to the appropriate Python type

        Parameters
        ----------
        value : str
            The cell value as text

        Returns
        -------
        object
            The most specialized type recognized
        """
        if value == 'null':
            return None
        if "|" in value and value.startswith("["):
            return [self._cast_value(v) for v in value.split("|")]
        # is it a parameter?
        elif value.startswith("["):
            return self._parse_param(value)
        else:
            # begin guessing dtype
            try:
                value = int(value)
            except ValueError:
                try:
                    value = float(value)
                except ValueError:
                    pass
            return value


class _MzTabTable(_MzTabParserBase):

    """An internal class for accumulating information about an single table
    represented in an mzTab file

    Attributes
    ----------
    header : list
        The column names for the table
    name : str
        The table's name, human readable
    rows : list
        An accumulator of table rows
    """

    def __init__(self, name, header=None, rows=None):
        if rows is None:
            rows = []
        self.name = name
        self.header = header
        self.rows = rows

    def __repr__(self):
        n_cols = len(self.header) if self.header is not None else 0
        n_rows = len(self.rows)
        template = "<_MzTabTable {name} with {n_cols} columns and {n_rows} rows>"
        return template.format(n_cols=n_cols, n_rows=n_rows, name=self.name)

    def add(self, row):
        self.rows.append([self._cast_value(v) for v in row])

    def as_dict(self):
        return [dict(zip(self.header, row)) for row in self.rows]

    def as_df(self, index=None):
        """Convert the table to a DataFrame in memory.

        Returns
        -------
        pd.DataFrame
        """
        table = pd.DataFrame(data=self.rows, columns=self.header)
        if index is not None and len(table.index) > 0:
            table = table.set_index(index, drop=False)
        table.name = self.name
        return table

    def clear(self):
        self.header = None
        self.rows = []


class MzTab(_MzTabParserBase):
    """Parser for mzTab format files.

    Attributes
    ----------
    comments : list
        A list of comments across the file
    file : _file_obj
        A file stream wrapper for the file to be read
    metadata : OrderedDict
        A mapping of metadata that was entities.
    peptide_table : _MzTabTable or pd.DataFrame
        The table of peptides. Not commonly used.
    protein_table : _MzTabTable or pd.DataFrame
        The table of protein identifications.
    small_molecule_table : _MzTabTable or pd.DataFrame
        The table of small molecule identifications.
    spectrum_match_table : _MzTabTable or pd.DataFrame
        The table of spectrum-to-peptide match identifications.
    """

    def __init__(self, path, encoding='utf8'):
        self.file = _file_obj(path, mode='r', encoding=encoding)
        self.metadata = OrderedDict()
        self.comments = []
        self._init_tables()
        self._parse()
        self._transform_tables()

    @property
    def version(self):
        return self.metadata['mzTab-version']

    @property
    def mode(self):
        return self.metadata['mzTab-mode']

    @property
    def type(self):
        return self.metadata['mzTab-type']

    def _collapse_properties(self, proplist):
        entities = OrderedDict()
        for key, value in proplist.items():
            try:
                entity, prop_name = key.rsplit("-", 1)
            except ValueError:
                continue
            try:
                entity_dict = entities[entity]
            except KeyError:
                entity_dict = entities[entity] = {}
            entity_dict[prop_name] = value
        for key, value in proplist.items():
            if key in entities:
                entity = entities[key]
                if 'name' not in entity:
                    entity['name'] = value
        return entities

    def __getitem__(self, key):
        key = key.lower().strip()
        if key in ('psm', ):
            return self.spectrum_match_table
        if key in ('pep', ):
            return self.peptide_table
        if key in ('prt', ):
            return self.protein_table
        if key in ('sml', ):
            return self.small_molecule_table
        else:
            raise KeyError(key)

    def __iter__(self):
        yield 'PRT', self.protein_table
        yield 'PEP', self.peptide_table
        yield 'PSM', self.spectrum_match_table
        yield 'SML', self.small_molecule_table

    def _init_tables(self):
        self.protein_table = _MzTabTable("protein")
        self.peptide_table = _MzTabTable("peptide")
        self.spectrum_match_table = _MzTabTable('psm')
        self.small_molecule_table = _MzTabTable('small molecule')

    def _transform_tables(self):
        self.protein_table = self.protein_table.as_df('accession')
        self.peptide_table = self.peptide_table.as_df()
        self.spectrum_match_table = self.spectrum_match_table.as_df('PSM_ID')
        self.small_molecule_table = self.small_molecule_table.as_df()

    def _parse(self):
        for i, line in enumerate(self.file):
            line = line.strip()
            tokens = line.split("\t")
            if not tokens:
                continue
            if tokens[0] == ("MTD"):
                name = tokens[1]
                value = self._cast_value(tokens[2])
                self.metadata[name] = value
            elif tokens[0] == 'COM':
                self.comments.append(self._cast_value(tokens[1]))
            # headers
            elif tokens[0] == "PRH":
                self.protein_table.header = tokens[1:]
            elif tokens[0] == "PEH":
                self.peptide_table.header = tokens[1:]
            elif tokens[0] == "PSH":
                self.spectrum_match_table.header = tokens[1:]
            elif tokens[0] == "SMH":
                self.small_molecule_table.header = tokens[1:]
            # rows
            elif tokens[0] == "PRT":
                self.protein_table.add(tokens[1:])
            elif tokens[0] == "PEP":
                self.peptide_table.add(tokens[1:])
            elif tokens[0] == "PSM":
                self.spectrum_match_table.add(tokens[1:])
            elif tokens[0] == "SML":
                self.small_molecule_table.add(tokens[1:])