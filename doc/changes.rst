.. |br| raw:: html

   <br />

.. _changes:

==============
Change History
==============

 * 18 May 14: **Picos** :ref:`1.0.1.dev <download>` **Released** |br|
   
   Major Release with following changes:
     * Support for Semidefinite Programming over the complex domain, see :ref:`here <complex>`.
     * Flow constraints in graphs, cf. :ref:`this section <flowcons>`.
     * Improved implementation of ``__getitem__`` for affine expressions. The slicing of affine expressions
       was slowing down (a lot!) the processing of the optimization problem.

 * 19 Jul. 13: **Picos** :ref:`1.0.0 <download>` **Released** |br|
   
   Major Release with following changes:
     * Semidefinite Programming Interface for MOSEK 7.0 !!!
     * New options ``handleBarVars`` and ``handleConeVars`` to customize how SOCP and SDPs are passed to MOSEK
       (When these options are set to ``True`` , PICOS tries to minimize the number of variables of the
       MOSEK instance, see the doc in :func:`set_all_options_to_default() <picos.Problem.set_all_options_to_default>`).
     * The function :func:`dualize() <picos.Problem.dualize>` returns the Lagrangian dual of a Problem.
     * The option ``solve_via_dual`` (documented in
       :func:`set_all_options_to_default() <picos.Problem.set_all_options_to_default>` ) allows the user to pass
       the dual of a problem to a solver, instead of the primal problem itself. This can yield important speed-up for
       certain problems.
     * In addition to the geometric mean function :func:`picos.geomean() <picos.tools.geomean>` , it is now possible
       to pass rational powers of affine expressions (through an overload of the ``**`` operator), trace of
       matrix powers with :func:`picos.tracepow() <picos.tools.tracepow>` , (generalized) p-norms
       with :func:`picos.norm() <picos.tools.norm>`, and nth root of a determinant with
       :func:`picos.detrootn() <picos.tools.detrootn>`. These functions automatically reformulate the entered inequalities as a set of equivalent SOCP or SDP constraints.
     * It is now possible to specify variable bounds directly (rather than adding constraints of the type ``x >= 0`` ).
       This can be done with the Keywords ``lower`` and ``upper`` of the function
       :func:`add_variable() <picos.Problem.add_variable>` ,
       or by the methods :func:`set_lower() <picos.Variable.set_lower>` ,
       :func:`set_upper() <picos.Variable.set_upper>` ,
       :func:`set_sparse_lower() <picos.Variable.set_sparse_lower>` , and
       :func:`set_sparse_upper() <picos.Variable.set_sparse_upper>` of the class :class:`Variable <picos.Variable>`.
     * It is now more efficient to update a Problem and resolve it. This is done thanks to the attribute ``passed``
       of the classes :class:`Constraint <picos.Constraint>` and :class:`Variable <picos.Variable>` ,
       that stores which solvers are already aware of a constraint / variable. There is also an
       attribute ``obj_passed`` of the class :class:`Problem <picos.Problem>` , that lists the solver instances
       where the objective function has already been passed. The option ``onlyChangeObjective`` has been
       deprecated.
       
     
 * 17 Apr. 13: **Picos** :ref:`0.1.3 <download>` **Released** |br|
   
   Major changes:
     * Function :func:`picos.geomean() <picos.tools.geomean>` implemented, to handle inequalities involving
       a geometric mean and reformulate them automatically as a set of SOCP constraints.
     * Some options were added for the function :func:`solve() <picos.Problem.solve>` ,
       to tell CPLEX to stop the computation as soon as a given value for the
       upper bound (or lower bound) is reached (see the options ``uboundlimit`` and ``lboundlimit``
       documented in :func:`set_all_options_to_default() <picos.Problem.set_all_options_to_default>`).
     * The time used by the solver is now stored in the dictionary
       returned by :func:`solve() <picos.Problem.solve>`.
     * The option ``boundMonitor`` of the function :func:`solve() <picos.Problem.solve>`
       gives access to the values of the lower and upper bounds over time with cplex.
       (this option is documented in :func:`set_all_options_to_default() <picos.Problem.set_all_options_to_default>`).
     * The weak inequalities operators ``<=`` and ``>=`` can now be used (but strict inequalities are
       still interpreted as weak inequalities !).
     * Minor bugs corrected (access to the duals of fixed variables with CPLEX,
       evaluation of constant affine expressions with a zero coefficient appearing
       in the dict of linear terms, number of constraints is now updated in
       :func:`remove_constraint() <picos.Problem.remove_constraint>`).

 * 10 Jan. 13: **Picos** :ref:`0.1.2 <download>` **Released** |br|
   
   Bug-fix release, correcting:
     * The :func:`write_to_file() <picos.Problem.write_to_file>`
       function for sparse SDPA files. The function was writing the
       coefficients of the lower triangular part of the constraint matrices
       instead of the upper triangle.
     * An ``IndexError`` occuring with the function
       :func:`remove_constraint() <picos.Problem.remove_constraint>`.
   
   Thanks to Warren Schudy for pointing out these bugs of the previous release !

 * 08 Dec. 12: **Picos** :ref:`0.1.1 <download>` **Released** |br|
   
   Major changes:
     * Picos now interfaces GUROBI !
     * You can specify an initial solution to *warm-start* mixed integer optimizers.
       (see the option ``hotstart`` documented in
       :func:`set_all_options_to_default() <picos.Problem.set_all_options_to_default>`)
     * Minor bugs with quadratic expressions corrected
     * It's possible to return a reference to a constraint added
       with add_constraint()